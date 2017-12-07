from datetime import datetime, timedelta, timezone
from collections import deque
from math import sqrt
from time import monotonic, time
from pkg_resources import resource_stream
from tempfile import TemporaryFile
from asyncio import gather, CancelledError, TimeoutError, Lock
from base64 import b64encode

from aiohttp import ClientError, ClientResponseError, ServerTimeoutError
from aiopogo import json_dumps, json_loads

from .utils import load_pickle, dump_pickle
from .db import session_scope, get_pokemon_ranking, estimate_remaining_time, FORT_CACHE
from .names import MOVES, POKEMON
from .shared import get_logger, SessionManager, LOOP, run_threaded
from . import sanitized as conf

import os

WEBHOOK = False
if conf.NOTIFY:
    TWITTER = False
    PUSHBULLET = False
    TELEGRAM = False

    if all((conf.TWITTER_CONSUMER_KEY, conf.TWITTER_CONSUMER_SECRET,
            conf.TWITTER_ACCESS_KEY, conf.TWITTER_ACCESS_SECRET)):
        try:
            from peony import PeonyClient
        except ImportError as e:
            raise ImportError("You specified a TWITTER_ACCESS_KEY but you don't have peony-twitter installed.") from e

        TWITTER=True

        if conf.TWEET_IMAGES:
            if conf.IMAGE_STATS and not conf.ENCOUNTER:
                raise ValueError('You enabled TWEET_STATS but ENCOUNTER is not set.')
            try:
                import cairo
            except ImportError as e:
                raise ImportError('You enabled TWEET_IMAGES but Cairo could not be imported.') from e

    if conf.PB_API_KEY:
        try:
            from asyncpushbullet import AsyncPushbullet
        except ImportError as e:
            raise ImportError("You specified a PB_API_KEY but you don't have asyncpushbullet installed.") from e
        PUSHBULLET=True

    if conf.WEBHOOKS:
        from aiopogo import json_dumps, json_loads

        if len(conf.WEBHOOKS) == 1:
            HOOK_POINT = next(iter(conf.WEBHOOKS))
            WEBHOOK = 1
        else:
            HOOK_POINTS = conf.WEBHOOKS
            WEBHOOK = 2

    if conf.TELEGRAM_BOT_TOKEN and conf.TELEGRAM_CHAT_ID:
        TELEGRAM=True

    NATIVE = TWITTER or PUSHBULLET or TELEGRAM

    if not (NATIVE or WEBHOOK):
        raise ValueError('NOTIFY is enabled but no keys or webhook address were provided.')

    try:
        if conf.INITIAL_SCORE < conf.MINIMUM_SCORE:
            raise ValueError('INITIAL_SCORE should be greater than or equal to MINIMUM_SCORE.')
    except TypeError:
        raise AttributeError('INITIAL_SCORE or MINIMUM_SCORE are not set.')

    if conf.NOTIFY_RANKING and conf.NOTIFY_IDS:
        raise ValueError('Only set NOTIFY_RANKING or NOTIFY_IDS, not both.')
    elif not any((conf.NOTIFY_RANKING, conf.NOTIFY_IDS, conf.ALWAYS_NOTIFY_IDS)):
        raise ValueError('Must set either NOTIFY_RANKING, NOTIFY_IDS, or ALWAYS_NOTIFY_IDS.')


class NotificationCache:
    def __init__(self):
        self.store = set()

    def __contains__(self, item):
        return item in self.store

    def add(self, item, delay):
        self.store.add(item)
        return LOOP.call_later(delay, self.remove, item)

    def remove(self, item):
        self.store.discard(item)


class PokeImage:
    def __init__(self, pokemon, move1, move2, time_of_day=0, stats=conf.IMAGE_STATS):
        self.pokemon_id = pokemon['pokemon_id']
        self.name = POKEMON[self.pokemon_id]
        self.time_of_day = time_of_day

        if stats:
            try:
                self.attack = pokemon['individual_attack']
                self.defense = pokemon['individual_defense']
                self.stamina = pokemon['individual_stamina']
            except KeyError:
                pass
            self.move1 = move1
            self.move2 = move2

    def create(self, stats=conf.IMAGE_STATS):
        if self.time_of_day > 1:
            bg = resource_stream('monocle', 'static/monocle-icons/assets/notification-bg-night.png')
        else:
            bg = resource_stream('monocle', 'static/monocle-icons/assets/notification-bg-day.png')
        ims = cairo.ImageSurface.create_from_png(bg)
        self.context = cairo.Context(ims)
        pokepic = resource_stream('monocle', 'static/monocle-icons/original-icons/{}.png'.format(self.pokemon_id))
        if stats:
            self.draw_stats()
        self.draw_image(pokepic, 204, 224)
        self.draw_name(50 if stats else 120)
        image = TemporaryFile(suffix='.png')
        ims.write_to_png(image)
        return image

    def draw_stats(self, iv_font=conf.IV_FONT, move_font=conf.MOVE_FONT):
        """Draw the Pokemon's IV's and moves."""

        self.context.set_line_width(1.75)
        text_x = 240

        try:
            self.context.select_font_face(conf.IV_FONT)
            self.context.set_font_size(22)

            # black stroke
            self.draw_ivs(text_x)
            self.context.set_source_rgba(0, 0, 0)
            self.context.stroke()

            # white fill
            self.context.move_to(text_x, 90)
            self.draw_ivs(text_x)
            self.context.set_source_rgba(1, 1, 1)
            self.context.fill()
        except AttributeError:
            pass

        if self.move1 or self.move2:
            self.context.select_font_face(conf.MOVE_FONT)
            self.context.set_font_size(16)

            # black stroke
            self.draw_moves(text_x)
            self.context.set_source_rgba(0, 0, 0)
            self.context.stroke()

            # white fill
            self.draw_moves(text_x)
            self.context.set_source_rgba(1, 1, 1)
            self.context.fill()

    def draw_ivs(self, text_x):
        self.context.move_to(text_x, 90)
        self.context.text_path("Attack:  {:>2}/15".format(self.attack))
        self.context.move_to(text_x, 116)
        self.context.text_path("Defense: {:>2}/15".format(self.defense))
        self.context.move_to(text_x, 142)
        self.context.text_path("Stamina: {:>2}/15".format(self.stamina))

    def draw_moves(self, text_x):
        if self.move1:
            self.context.move_to(text_x, 170)
            self.context.text_path("Move 1: {}".format(self.move1))
        if self.move2:
            self.context.move_to(text_x, 188)
            self.context.text_path("Move 2: {}".format(self.move2))

    def draw_image(self, pokepic, height, width):
        """Draw a scaled image on a given context."""
        ims = cairo.ImageSurface.create_from_png(pokepic)
        # calculate proportional scaling
        img_height = ims.get_height()
        img_width = ims.get_width()
        width_ratio = width / img_width
        height_ratio = height / img_height
        scale_xy = min(height_ratio, width_ratio)
        # scale image and add it
        self.context.save()
        if scale_xy < 1:
            self.context.scale(scale_xy, scale_xy)
            if scale_xy == width_ratio:
                new_height = img_height * scale_xy
                top = (height - new_height) / 2
                self.context.translate(8, top + 8)
            else:
                new_width = img_width * scale_xy
                left = (width - new_width) / 2
                self.context.translate(left + 8, 8)
        else:
            left = (width - img_width) / 2
            top = (height - img_height) / 2
            self.context.translate(left + 8, top + 8)
        self.context.set_source_surface(ims)
        self.context.paint()
        self.context.restore()

    def draw_name(self, pos, font=conf.NAME_FONT):
        """Draw the Pokemon's name."""
        self.context.set_line_width(2.5)
        text_x = 240
        text_y = pos
        self.context.select_font_face(font)
        self.context.set_font_size(32)
        self.context.move_to(text_x, text_y)
        self.context.set_source_rgba(0, 0, 0)
        self.context.text_path(self.name)
        self.context.stroke()
        self.context.move_to(text_x, text_y)
        self.context.set_source_rgba(1, 1, 1)
        self.context.show_text(self.name)


class Notification:
    def __init__(self, pokemon, score, time_of_day):
        self.pokemon = pokemon
        self.name = POKEMON[pokemon['pokemon_id']]
        self.coordinates = pokemon['lat'], pokemon['lon']
        self.score = score
        self.time_of_day = time_of_day
        self.log = get_logger('notifier')
        self.description = 'wild'
        try:
            self.move1 = MOVES[pokemon['move_1']]
            self.move2 = MOVES[pokemon['move_2']]
        except KeyError:
            self.move1 = None
            self.move2 = None

        try:
            if 'raid' in pokemon:
                self.description = 'raid'
            else:
                if self.score == 1:
                    self.description = 'perfect'
                elif self.score > .83:
                    self.description = 'great'
                elif self.score > .6:
                    self.description = 'good'
        except TypeError:
            pass

        if conf.TZ_OFFSET:
            _tz = timezone(timedelta(hours=conf.TZ_OFFSET))
        else:
            _tz = None
        now = datetime.fromtimestamp(pokemon['seen'], _tz)

        if TWITTER and conf.HASHTAGS:
            self.hashtags = conf.HASHTAGS.copy()
        else:
            self.hashtags = set()

        # check if expiration time is known, or a range
        try:
            self.tth = pokemon['time_till_hidden']
            delta = timedelta(seconds=self.tth)
            self.expire_time = (now + delta).strftime('%I:%M %p').lstrip('0')
        except KeyError:
            self.earliest_tth = pokemon['earliest_tth']
            self.latest_tth = pokemon['latest_tth']
            min_delta = timedelta(seconds=self.earliest_tth)
            max_delta = timedelta(seconds=self.latest_tth)
            self.earliest = now + min_delta
            self.latest = now + max_delta

            # check if the two TTHs end on same minute
            if (self.earliest.minute == self.latest.minute
                    and self.earliest.hour == self.latest.hour):
                self.tth = (self.earliest_tth + self.latest_tth) / 2
                self.delta = timedelta(seconds=self.tth)
                self.expire_time = (
                    now + self.delta).strftime('%I:%M %p').lstrip('0')
            else:
                self.min_expire_time = (
                    now + min_delta).strftime('%I:%M').lstrip('0')
                self.max_expire_time = (
                    now + max_delta).strftime('%I:%M %p').lstrip('0')

        self.map_link = 'https://maps.google.com/maps?q={0[0]:.5f},{0[1]:.5f}'.format(self.coordinates)
        self.place = None

    async def notify(self):
        if conf.LANDMARKS and (TWITTER or PUSHBULLET):
            self.landmark = conf.LANDMARKS.find_landmark(self.coordinates)

        try:
            self.place = self.landmark.generate_string(self.coordinates)
            if TWITTER and self.landmark.hashtags:
                self.hashtags.update(self.landmark.hashtags)
        except AttributeError:
            self.place = self.generic_place_string()

        if PUSHBULLET or TELEGRAM:
            try:
                self.attack = self.pokemon['individual_attack']
                self.defense = self.pokemon['individual_defense']
                self.stamina = self.pokemon['individual_stamina']
            except KeyError:
                pass

        tweeted = False
        pushed = False
        telegram = False

        notifications = []
        if PUSHBULLET:
            notifications.append(self.pbpush())

        if TWITTER:
            notifications.append(self.tweet())

        if TELEGRAM:
            notifications.append(self.sendToTelegram())

        results = await gather(*notifications, loop=LOOP)
        return True in results

    async def sendToTelegram(self):
        session = SessionManager.get()
        title = self.name
        try:
            minutes, seconds = divmod(self.tth, 60)
            description = 'Expires at: {} ({:.0f}m{:.0f}s left)'.format(self.expire_time, minutes, seconds)
        except AttributeError:
            description = "It'll expire between {} & {}.".format(self.min_expire_time, self.max_expire_time)

        try:
            title += ' ({}/{}/{})'.format(self.attack, self.defense, self.stamina)
        except AttributeError:
            pass

        if conf.TELEGRAM_MESSAGE_TYPE == 0:
            TELEGRAM_BASE_URL = "https://api.telegram.org/bot{token}/sendVenue".format(token=conf.TELEGRAM_BOT_TOKEN)
            payload = {
                'chat_id': conf.TELEGRAM_CHAT_ID,
		        'latitude': self.coordinates[0],
		        'longitude': self.coordinates[1],
		        'title' : title,
		        'address' : description,
		    }
        else:
            TELEGRAM_BASE_URL = "https://api.telegram.org/bot{token}/sendMessage".format(token=conf.TELEGRAM_BOT_TOKEN)
            map_link = '<a href="http://maps.google.com/maps?q={},{}">Open GMaps</a>'.format(self.coordinates[0], self.coordinates[1])
            payload = {
                'chat_id': conf.TELEGRAM_RAIDS_CHAT_ID,
                'parse_mode': 'HTML',
                'text' : title + '\n' + description + '\n\n' + map_link
            }


        try:
            async with session.post(TELEGRAM_BASE_URL, data=payload) as resp:
                self.log.info('Sent a Telegram notification about {}.', self.name)
                return True
        except ClientResponseError as e:
            self.log.error('Error {} from Telegram: {}', e.code, e.message)
        except ClientError as e:
            self.log.error('{} during Telegram notification.', e.__class__.__name__)
        except CancelledError:
            raise
        except Exception:
            self.log.exception('Exception caught in Telegram notification.')
        return False

    async def pbpush(self):
        """ Send a PushBullet notification either privately or to a channel,
        depending on whether or not PB_CHANNEL is set in config.
        """

        pb = self.get_pushbullet_client()

        description = self.description
        try:
            if self.score < .45:
                description = 'weak'
            elif self.score < .35:
                description = 'bad'
        except TypeError:
            pass

        try:
            expiry = 'until {}'.format(self.expire_time)
            minutes, seconds = divmod(self.tth, 60)
            remaining = 'for {:.0f}m{:.0f}s'.format(minutes, seconds)
        except AttributeError:
            expiry = 'until between {} and {}'.format(self.min_expire_time, self.max_expire_time)
            minutes, seconds = divmod(self.earliest_tth, 60)
            min_remaining = '{:.0f}m{:.0f}s'.format(minutes, seconds)
            minutes, seconds = divmod(self.latest_tth, 60)
            max_remaining = '{:.0f}m{:.0f}s'.format(minutes, seconds)
            remaining = 'for between {} and {}'.format(min_remaining, max_remaining)

        title = 'A {} {} will be in {} {}!'.format(description, self.name, conf.AREA_NAME, expiry)

        body = 'It will be {} {}.\n\n'.format(self.place, remaining)
        try:
            body += ('Attack: {}\n'
                     'Defense: {}\n'
                     'Stamina: {}\n'
                     'Move 1: {}\n'
                     'Move 2: {}\n\n').format(self.attack, self.defense, self.stamina, self.move1, self.move2)
        except AttributeError:
            pass

        try:
            try:
                channel = pb.channels[conf.PB_CHANNEL]
            except (IndexError, KeyError):
                channel = None
            await pb.async_push_link(title, self.map_link, body, channel=channel)
        except Exception:
            self.log.exception('Failed to send a PushBullet notification about {}.', self.name)
            return False
        else:
            self.log.info('Sent a PushBullet notification about {}.', self.name)
            return True

    def shorten_tweet(self, tweet_text):
        tweet_text = tweet_text.replace(' meters ', 'm ')

        # remove hashtags until length is short enough
        while len(tweet_text) > 116:
            if self.hashtags:
                hashtag = self.hashtags.pop()
                tweet_text = tweet_text.replace(' #' + hashtag, '')
            else:
                break

        try:
            if len(tweet_text) > 116:
                tweet_text = tweet_text.replace(self.landmark.name,
                                                self.landmark.shortname)
            else:
                return tweet_text

            if len(tweet_text) > 116:
                place = self.landmark.shortname or self.landmark.name
                phrase = self.landmark.phrase
                if self.place.startswith(phrase):
                    place_string = '{} {}'.format(phrase, place)
                else:
                    place_string = 'near {}'.format(place)
                tweet_text = tweet_text.replace(self.place, place_string)
            else:
                return tweet_text
        except AttributeError:
            pass

        if len(tweet_text) > 116:
            try:
                tweet_text = 'A {d} {n} will be {p} until {e}.'.format(
                             d=self.description, n=self.name,
                             p=place_string, e=self.expire_time)
            except AttributeError:
                tweet_text = (
                    "A {d} {n} appeared {p}! It'll expire between {e1} & {e2}."
                    ).format(d=self.description, n=self.name, p=place_string,
                             e1=self.min_expire_time, e2=self.max_expire_time)
        else:
            return tweet_text

        if len(tweet_text) > 116:
            try:
                tweet_text = 'A {d} {n} will expire at {e}.'.format(
                             n=self.name, e=self.expire_time)
            except AttributeError:
                tweet_text = (
                    'A {d} {n} will expire between {e1} & {e2}.').format(
                    d=self.description, n=self.name, e1=self.min_expire_time,
                    e2=self.max_expire_time)
        else:
            return tweet_text

    async def tweet(self):
        """ Create message, reduce it until it fits in a tweet, and then tweet
        it with a link to Google maps and tweet location included.
        """

        tag_string = ''
        try:
            for hashtag in self.hashtags:
                tag_string += ' #{}'.format(hashtag)
        except TypeError:
            pass

        try:
            tweet_text = (
                'A {d} {n} appeared! It will be {p} until {e}. {t}').format(
                d=self.description, n=self.name, p=self.place,
                e=self.expire_time, t=tag_string)
        except AttributeError:
            tweet_text = (
                'A {d} {n} appeared {p}! It will expire sometime between '
                '{e1} and {e2}. {t}').format(
                d=self.description, n=self.name, p=self.place,
                e1=self.min_expire_time, e2=self.max_expire_time,
                t=tag_string)

        if len(tweet_text) > 116:
            tweet_text = self.shorten_tweet(tweet_text)

        tweet_text += ' ' + self.map_link

        media_id = None
        client = self.get_twitter_client()
        if conf.TWEET_IMAGES:
            try:
                image = PokeImage(self.pokemon, self.move1, self.move2, self.time_of_day).create()
            except Exception:
                self.log.exception('Failed to create a Tweet image.')
            else:
                try:
                    media = await client.upload_media(image,
                        media_type='image/png',
                        media_category='tweet_image',
                        chunked=True)
                    media_id = media['media_id']
                except Exception:
                    self.log.exception('Failed to upload Tweet image.')
        try:
            await client.api.statuses.update.post(
                status=tweet_text,
                media_ids=media_id,
                lat=str(self.coordinates[0]),
                long=str(self.coordinates[1]),
                display_coordinates=True)
        except Exception:
            self.log.exception('Failed to tweet about {}.', self.name)
            return False
        else:
            self.log.info('Sent a tweet about {}.', self.name)
            return True
        finally:
            try:
                image.close()
            except AttributeError:
                pass

    @staticmethod
    def generic_place_string():
        """ Create a place string with area name (if available)"""
        # no landmarks defined, just use area name
        place = 'in {}'.format(conf.AREA_NAME)
        return place

    @classmethod
    def get_pushbullet_client(cls):
        try:
            return cls._pushbullet_client
        except AttributeError:
            cls._pushbullet_client = AsyncPushbullet(
                api_key=conf.PB_API_KEY,
                loop=LOOP)
            return cls._pushbullet_client

    @classmethod
    def get_twitter_client(cls):
        try:
            return cls._twitter_client
        except AttributeError:
            cls._twitter_client = PeonyClient(
                consumer_key=conf.TWITTER_CONSUMER_KEY,
                consumer_secret=conf.TWITTER_CONSUMER_SECRET,
                access_token=conf.TWITTER_ACCESS_KEY,
                access_token_secret=conf.TWITTER_ACCESS_SECRET,
                session=SessionManager.get(),
                loop=LOOP)
            return cls._twitter_client


class Notifier:
    
    db_access_lock = Lock(loop=LOOP)

    def __init__(self):
        self.cache = NotificationCache()
        self.notify_ranking = conf.NOTIFY_RANKING
        self.initial_score = conf.INITIAL_SCORE
        self.minimum_score = conf.MINIMUM_SCORE
        self.last_notification = monotonic() - (conf.FULL_TIME / 2)
        self.always_notify = []
        self.log = get_logger('notifier')
        self.never_notify = conf.NEVER_NOTIFY_IDS
        self.rarity_override = conf.RARITY_OVERRIDE
        self.sent = 0
        if self.notify_ranking:
            self.initialize_ranking()
            LOOP.call_later(3600, self.set_notify_ids)
        elif conf.NOTIFY_IDS or conf.ALWAYS_NOTIFY_IDS:
            self.notify_ids = conf.NOTIFY_IDS or conf.ALWAYS_NOTIFY_IDS
            self.always_notify = conf.ALWAYS_NOTIFY_IDS
            self.notify_ranking = len(self.notify_ids)

    def set_notify_ids(self):
        LOOP.create_task(self._set_notify_ids())
        LOOP.call_later(3600, self.set_notify_ids)

    async def _set_notify_ids(self):
        await run_threaded(self.set_ranking)
        self.notify_ids = self.pokemon_ranking[0:self.notify_ranking]
        self.always_notify = set(self.pokemon_ranking[0:conf.ALWAYS_NOTIFY])
        self.always_notify |= set(conf.ALWAYS_NOTIFY_IDS)
        self.log.info('Updated Pokemon rankings.')

    def initialize_ranking(self):
        self.pokemon_ranking = load_pickle('ranking')
        if self.pokemon_ranking:
            self.notify_ids = self.pokemon_ranking[0:self.notify_ranking]
            self.always_notify = set(self.pokemon_ranking[0:conf.ALWAYS_NOTIFY])
            self.always_notify |= set(conf.ALWAYS_NOTIFY_IDS)
        else:
            LOOP.run_until_complete(self._set_notify_ids())

    def set_ranking(self):
        try:
            with session_scope() as session:
                self.pokemon_ranking = get_pokemon_ranking(session)
        except Exception:
            self.log.exception('An exception occurred while trying to update rankings.')
        else:
            dump_pickle('ranking', self.pokemon_ranking)

    def get_rareness_score(self, pokemon_id):
        if pokemon_id in self.rarity_override:
            return self.rarity_override[pokemon_id]
        exclude = len(self.always_notify)
        total = self.notify_ranking - exclude
        ranking = self.notify_ids.index(pokemon_id) - exclude
        percentile = 1 - (ranking / total)
        return percentile

    def get_required_score(self, now=None):
        if self.initial_score == self.minimum_score or conf.FULL_TIME == 0:
            return self.initial_score
        now = now or monotonic()
        time_passed = now - self.last_notification
        subtract = self.initial_score - self.minimum_score
        if time_passed < conf.FULL_TIME:
            subtract *= (time_passed / conf.FULL_TIME)
        return self.initial_score - subtract

    def eligible(self, pokemon):
        pokemon_id = pokemon['pokemon_id']

        unique_id = self.unique_id(pokemon)

        if pokemon_id in self.never_notify:
            return False
        if pokemon_id in self.always_notify:
            return unique_id not in self.cache
        if (pokemon_id not in self.notify_ids
                and pokemon_id not in self.rarity_override):
            return False
        if conf.IGNORE_RARITY:
            return unique_id not in self.cache
        try:
            if pokemon['time_till_hidden'] < conf.TIME_REQUIRED:
                return False
        except KeyError:
            pass
        if unique_id in self.cache:
            return False

        rareness = self.get_rareness_score(pokemon_id)
        highest_score = (rareness + 1) / 2
        score_required = self.get_required_score()
        return highest_score > score_required

    def cleanup(self, unique_id, handle):
        self.cache.remove(unique_id)
        handle.cancel()
        return False

    def unique_id(self, obj):
        if 'encounter_id' in obj:
            unique_id = obj['encounter_id']
        elif 'external_id' in obj:
            unique_id = "e{}".format(obj['external_id'])
        return unique_id 

    async def notify(self, pokemon, time_of_day):
        """Send a PushBullet notification and/or a Tweet, depending on if their
        respective API keys have been set in config.
        """
        whpushed = False
        notified = False

        pokemon_id = pokemon['pokemon_id']
        name = POKEMON[pokemon_id]

        unique_id = self.unique_id(pokemon)

        if unique_id in self.cache:
            self.log.info("{} was already notified about.", name)
            return False

        now = monotonic()
        if pokemon_id in self.always_notify:
            score_required = 0
        else:
            score_required = self.get_required_score(now)

        try:
            iv_score = (pokemon['individual_attack'] + pokemon['individual_defense'] + pokemon['individual_stamina']) / 45
        except KeyError:
            if conf.IGNORE_IVS:
                iv_score = None
            else:
                self.log.warning('IVs are supposed to be considered but were not found.')
                return False

        if score_required:
            if conf.IGNORE_RARITY:
                score = iv_score
            elif conf.IGNORE_IVS:
                score = self.get_rareness_score(pokemon_id)
            else:
                rareness = self.get_rareness_score(pokemon_id)
                score = (iv_score + rareness) / 2
        else:
            score = 1

        if score < score_required:
            try:
                self.log.info("{}'s score was {:.3f} (iv: {:.3f}),"
                                 " but {:.3f} was required.",
                                 name, score, iv_score if iv_score is not None else -1, score_required)
            except TypeError:
                pass
            return False

        if 'time_till_hidden' not in pokemon:
            seen = pokemon['seen'] % 3600
            cache_handle = self.cache.store.add(unique_id)
            try:
                async with self.db_access_lock:
                    with session_scope() as session:
                        tth = await run_threaded(estimate_remaining_time, session, pokemon['spawn_id'], seen)
            except Exception:
                self.log.exception('An exception occurred while trying to estimate remaining time.')
                now_epoch = time()
                tth = (pokemon['seen'] + 90 - now_epoch, pokemon['seen'] + 3600 - now_epoch)
            LOOP.call_later(tth[1], self.cache.remove, unique_id)
            if pokemon_id not in self.always_notify:
                mean = sum(tth) / 2
                if mean < conf.TIME_REQUIRED:
                    self.log.info('{} has only around {} seconds remaining.', name, mean)
                    return False
            pokemon['earliest_tth'], pokemon['latest_tth'] = tth
        else:
            cache_handle = self.cache.add(unique_id, pokemon['time_till_hidden'])

        if WEBHOOK and NATIVE:
            notified, whpushed = await gather(
                Notification(pokemon, iv_score, time_of_day).notify(),
                self.webhook(pokemon),
                loop=LOOP)
        elif NATIVE:
            notified = await Notification(pokemon, iv_score, time_of_day).notify()
        elif WEBHOOK:
            whpushed = await self.webhook(pokemon)

        if notified or whpushed:
            self.last_notification = monotonic()
            self.sent += 1
            return True
        else:
            return self.cleanup(unique_id, cache_handle)


    async def webhook_raid(self, raid, fort):
        if not WEBHOOK:
            return

        if raid['fort_external_id'] in FORT_CACHE.gym_names:
            gym_name, gym_url = FORT_CACHE.gym_names[raid['fort_external_id']] 
        else:
            gym_name, gym_url = None, None

        m = conf.WEBHOOK_RAID_MAPPING
        data = {
            'type': "raid",
            'message': {
                m.get("raid_seed", "raid_seed"): raid['external_id'],
                m.get("latitude", "latitude"): fort['lat'],
                m.get("longitude", "longitude"): fort['lon'],
                m.get("level", "level"): raid['level'],
                m.get("pokemon_id", "pokemon_id"): raid['pokemon_id'],
                m.get("team", "team"): fort['team'],
                m.get("cp", "cp"): raid['cp'],
                m.get("move_1", "move_1"): raid['move_1'],
                m.get("move_2", "move_2"): raid['move_2'],
                m.get("raid_begin", "raid_begin"): raid['time_battle'],
                m.get("raid_end", "raid_end"): raid['time_end'],
                m.get("gym_id", "gym_id"): raid["fort_external_id"],
                m.get("base64_gym_id", "base64_gym_id"): b64encode(raid['fort_external_id'].encode('utf-8')),
                m.get("gym_name", "gym_name"): gym_name,
                m.get("gym_url", "gym_url"): gym_url,
            }
        }

        result = await self.wh_send(SessionManager.get(), data)
        self.last_notification = monotonic()
        self.sent += 1
        return result

    async def scan_log_webhook(self, title, message, embed_color):
        self.log.info('Beginning scan log webhook consruction: {}', title)
        if conf.SCAN_LOG_WEBHOOK:            
            payload = {
                'embeds': [{
                    'title': title,
                    'description': '{}\n\nSource: {}\nPath: {}'.format(message, conf.AREA_NAME, os.path.realpath(__file__)),
                    'color': embed_color
                }]
            }

            session = SessionManager.get()
            return await self.hook_post(conf.SCAN_LOG_WEBHOOK, session, payload)
        else:
            return


    async def notify_raid(self, fort):
        discord = False
        telegram = False
        if conf.RAIDS_DISCORD_URL:
            discord = await self.notify_raid_to_discord(fort)
        if conf.TELEGRAM_BOT_TOKEN and conf.TELEGRAM_RAIDS_CHAT_ID:
            telegram = await self.notify_raid_to_telegram(fort)
        if discord or telegram:
            self.last_notification = monotonic()
            self.sent += 1

    async def notify_raid_to_discord(self, fort):
        raid = fort.raid_info

        if raid.raid_pokemon.pokemon_id not in conf.RAIDS_IDS:
            if raid.raid_level < conf.RAIDS_LVL_MIN:
                return

        tth = raid.raid_battle_ms // 1000 if raid.raid_pokemon.pokemon_id == 0 else raid.raid_end_ms // 1000
        timer_end = datetime.fromtimestamp(tth, None)
        time_left = timedelta(seconds=tth - time())

        payload = {
            'username': 'Egg' if raid.raid_pokemon.pokemon_id == 0 else POKEMON[raid.raid_pokemon.pokemon_id],
            'embeds': [{
                'title': 'Raid{}'.format(raid.raid_level),
                'url': self.get_gmaps_link(fort.latitude, fort.longitude),
                'description': '{} ({}h {}mn {}s)'.format(timer_end.strftime("%H:%M:%S"), time_left.seconds // 3600, (time_left.seconds // 60) % 60, time_left.seconds % 60),
                'thumbnail': {'url': conf.ICONS_URL.format(raid.raid_pokemon.pokemon_id)},
                'image': {'url': self.get_static_map_url(fort.latitude, fort.longitude)}
            }]
        }

        session = SessionManager.get()
        return await self.hook_post(conf.RAIDS_DISCORD_URL, session, payload)

    async def notify_raid_to_telegram(self, fort):
        raid = fort.raid_info

        if raid.raid_pokemon.pokemon_id not in conf.RAIDS_IDS:
            if raid.raid_level < conf.RAIDS_LVL_MIN:
                return

        
        title = '[Raid lvl.{}] {}'.format(raid.raid_level, 'Egg' if raid.raid_pokemon.pokemon_id == 0 else POKEMON[raid.raid_pokemon.pokemon_id])
        tth = raid.raid_battle_ms // 1000 if raid.raid_pokemon.pokemon_id == 0 else raid.raid_end_ms // 1000
        timer_end = datetime.fromtimestamp(tth, None)
        time_left = timedelta(seconds=tth - time())
        description = '{} ({}h {}mn {}s)'.format(timer_end.strftime("%H:%M:%S"), time_left.seconds // 3600, (time_left.seconds // 60) % 60, time_left.seconds % 60)

        if conf.TELEGRAM_MESSAGE_TYPE == 0:
            TELEGRAM_BASE_URL = "https://api.telegram.org/bot{token}/sendVenue".format(token=conf.TELEGRAM_BOT_TOKEN)
            payload = {
                'chat_id': conf.TELEGRAM_RAIDS_CHAT_ID,
                'latitude': fort.latitude,
                'longitude': fort.longitude,
                'title' : title,
                'address' : description,
            }
        else:
            TELEGRAM_BASE_URL = "https://api.telegram.org/bot{token}/sendMessage".format(token=conf.TELEGRAM_BOT_TOKEN)
            map_link = '<a href="{}">Open GMaps</a>'.format(self.get_gmaps_link(fort.latitude, fort.longitude))
            payload = {
                'chat_id': conf.TELEGRAM_RAIDS_CHAT_ID,
                'parse_mode': 'HTML',
                'text' : title + '\n' + description + '\n\n' + map_link
            }
        
        session = SessionManager.get()
        return await self.hook_post(TELEGRAM_BASE_URL, session, payload, timeout=8)

    def get_gmaps_link(self, lat, lng):
        return 'http://maps.google.com/maps?q={},{}'.format(repr(lat), repr(lng))

    def get_static_map_url(self, lat, lng):
        center = '{},{}'.format(lat, lng)
        query_center = 'center={}'.format(center)
        query_markers = 'markers=color:red%7C{}'.format(center)
        query_size = 'size={}x{}'.format('250', '125')
        query_zoom = 'zoom={}'.format('15')
        query_maptype = 'maptype={}'.format('roadmap')

        url = ('https://maps.googleapis.com/maps/api/staticmap?' +
                query_center + '&' + query_markers + '&' +
                query_maptype + '&' + query_size + '&' + query_zoom)
        return url

    async def webhook(self, pokemon):
        """ Send a notification via webhook
        """
        try:
            tth = pokemon['time_till_hidden']
            ts = pokemon['expire_timestamp']
        except KeyError:
            tth = pokemon['earliest_tth']
            ts = pokemon['seen'] + tth

        data = {
            'type': "pokemon",
            'message': {
                "pokemon_id": pokemon['pokemon_id'],
                "encounter_id": pokemon['encounter_id'],
                "latitude": pokemon['lat'],
                "longitude": pokemon['lon'],
                "last_modified_time": pokemon['seen'] * 1000,
                "spawnpoint_id": pokemon['spawn_id'],
                "disappear_time": ts,
                "time_until_hidden_ms": tth * 1000,
                "pokemon_level": pokemon.get('level'),
                "cp": pokemon.get('cp'),
                "height": pokemon.get('height'),
                "weight": pokemon.get('weight'),
                "gender": pokemon.get('gender'),
                "form": pokemon.get('form'),
                "move_1": pokemon.get('move_1'),
                "move_2": pokemon.get('move_2'),
                "individual_attack": pokemon.get('individual_attack'),
                "individual_defense": pokemon.get('individual_defense'),
                "individual_stamina": pokemon.get('individual_stamina'),
            }
        }

        session = SessionManager.get()
        return await self.wh_send(session, data)


    if WEBHOOK > 1:
        async def wh_send(self, session, payload):
            results = await gather(*tuple(self.hook_post(w, session, payload) for w in HOOK_POINTS), loop=LOOP)
            return True in results
    else:
        async def wh_send(self, session, payload):
            return await self.hook_post(HOOK_POINT, session, payload)


    async def hook_post(self, w, session, payload, headers={'content-type': 'application/json'}, timeout=4):
        try:
            async with session.post(w, json=payload, timeout=timeout, headers=headers) as resp:
                return True
        except ClientResponseError as e:
            self.log.error('Error {} from webook {}: {}', e.code, w, e.message)
        except (TimeoutError, ServerTimeoutError):
            self.log.error('Response timeout from webhook: {}', w)
        except ClientError as e:
            self.log.error('{} on webhook: {}', e.__class__.__name__, w)
        except CancelledError:
            raise
        except Exception:
            self.log.exception('Error from webhook: {}', w)
        return False
