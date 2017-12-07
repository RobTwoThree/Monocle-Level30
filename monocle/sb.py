from time import time
from contextlib import contextmanager

from .shared import get_logger, SessionManager, LOOP
from .notification import Notifier
from . import sanitized as conf

log = get_logger("sb-detector")

SB_START = 0
SB_RAN = 1
SB_SIGHTING = 2
SB_UNCOMMON = 3
SB_ENC_MISS = 4
SB_VISIT = 5
SB_EMPTY_VISIT = 6

class SbAccountException(Exception):
    """Raised when an account is shadow banned"""

class SbDetector:
        
    sb_cooldown = min(max(30, conf.GRID[0] * conf.GRID[1]), 300)

    def __init__(self):
        if conf.SB_WEBHOOK:
            self.notifier = Notifier()
        else:
            self.notifier = None
        log.info("SbDetector initialized with cooldown: {}s.", self.sb_cooldown)

    def new_quarantine(self):
        return [int(time()), 0, 0, 0, 0, 0, 0]

    def reset_quarantine(self, quarantine):
        quarantine[SB_START] = int(time())
        quarantine[SB_RAN] = 0
        quarantine[SB_SIGHTING] = 0
        quarantine[SB_UNCOMMON] = 0
        quarantine[SB_ENC_MISS] = 0
        quarantine[SB_VISIT] = 0
        quarantine[SB_EMPTY_VISIT] = 0

    @contextmanager
    def quarantine(self, account):
        quarantine = account.get('sb_quarantine')

        if not quarantine or len(quarantine) < 7:
            quarantine = self.new_quarantine()

        yield quarantine

        account['sb_quarantine'] = quarantine 
                
    def add_sighting(self, account, sighting):
        with self.quarantine(account) as quarantine:
            quarantine[SB_SIGHTING] += 1
            pokemon_id = sighting.get('pokemon_id')
            if pokemon_id and pokemon_id not in conf.SB_COMMON_POKEMON_IDS:
                quarantine[SB_UNCOMMON] += 1

    def add_encounter_miss(self, account):
        with self.quarantine(account) as quarantine:
            quarantine[SB_ENC_MISS] += 1

    def add_visit(self, account):
        with self.quarantine(account) as quarantine:
            quarantine[SB_VISIT] += 1

    def add_empty_visit(self, account):
        with self.quarantine(account) as quarantine:
            quarantine[SB_EMPTY_VISIT] += 1

    async def detect(self, account):
        username = account.get('username')
        with self.quarantine(account) as quarantine:
            ran_at = quarantine[SB_RAN]

            if time() - ran_at < self.sb_cooldown:
                return

            quarantine[SB_RAN] = int(time())

            elapsed = int(time() - quarantine[SB_START])
            sightings = quarantine[SB_SIGHTING]
            uncommon = quarantine[SB_UNCOMMON]
            enc_miss = quarantine[SB_ENC_MISS]
            visits = quarantine[SB_VISIT]
            empty_visits = quarantine[SB_EMPTY_VISIT]

            try:
                if visits >= conf.SB_QUARANTINE_VISITS and empty_visits < sightings and sightings > 0 and uncommon <= 0:
                    raise SbAccountException("No uncommons seen after {} visits".format(conf.SB_QUARANTINE_VISITS))

                if sightings > conf.SB_MIN_SIGHTING_COUNT and uncommon <= 0:
                    raise SbAccountException("No uncommons seen after {} sightings".format(sightings))

                if enc_miss >= conf.SB_MAX_ENC_MISS and uncommon <= 0:
                    raise SbAccountException("Encounter missed for {} times".format(enc_miss))

                if quarantine[SB_VISIT] > conf.SB_QUARANTINE_VISITS:
                    self.reset_quarantine(quarantine)

                log.info("Username: {}(Lv.{}), visits: ({}/{}), empty: {}, sightings: {}, uncommon: {}, enc_miss: {}, quarantined: {}s, sbanned: {}",
                        username,
                        account.get('level',0),
                        visits, conf.SB_QUARANTINE_VISITS,
                        empty_visits,
                        sightings,
                        uncommon,
                        enc_miss,
                        elapsed,
                        False)
                return

            except SbAccountException as e:
                log.info("Username: {}(Lv.{}), visits: ({}/{}), empty: {}, sightings: {}, uncommon: {}, enc_miss: {}, quarntined: {}s, sbanned: {} ({})",
                        username,
                        account.get('level',0),
                        visits, conf.SB_QUARANTINE_VISITS,
                        empty_visits,
                        sightings,
                        uncommon,
                        enc_miss,
                        elapsed,
                        True,
                        e)
                if self.notifier:
                    LOOP.create_task(self.webhook(self.notifier, conf.SB_WEBHOOK, username,
                        message="{}\nlevel: {}, visits: ({}/{}), empty: {}, sightings: {}, uncommon: {}, enc_miss: {}, quarantined: {}s".format(e,
                            account.get('level',0), visits, conf.SB_QUARANTINE_VISITS,
                            empty_visits, sightings, uncommon, enc_miss, elapsed)))
                raise e

    async def webhook(self, notifier, endpoint, username, message):
        """ Send a notification via webhook
        """
        payload = {
            'embeds': [{
                'title': '{} sbanned in {}'.format(username, conf.INSTANCE_ID),
                'description': message,
                'color': '16060940', 
            }]
        }
        session = SessionManager.get()
        return await notifier.hook_post(endpoint, session, payload)
