import traceback
from math import ceil
from queue import PriorityQueue
from time import time, monotonic
from asyncio import CancelledError, Semaphore, sleep
from random import random

from pogeo import get_distance

from .db import SightingCache, Sighting, Spawnpoint, session_scope
from .utils import randomize_point
from .worker import Worker, UNIT, sb_detector
from .shared import LOOP, call_at, get_logger
from .accounts import get_accounts30, Account
from . import db_proc, bounds, spawns, sanitized as conf

log = get_logger("worker30")

HARDCORE_HYPERDRIVE = not conf.LV30_GMO

class EncounterSkippedError(Exception):
    """Raised when encounter is skipped without retry"""
    pass

class LateEncounterSkippedError(EncounterSkippedError):
    """Raised when encounter is skipped without retry due to insufficient time"""
    pass

class RetriableEncounterSkippedError(EncounterSkippedError):
    """Raised when encounter is skipped and should be retried"""
    pass

class Worker30(Worker):
    workers = [] 
    encounters = 0
    skipped = 0
    lates = 0
    visits = 0
    hash_burn = 0
    workers_needed = int(ceil(conf.LV30_PERCENT_OF_WORKERS * conf.GRID[0] * conf.GRID[1]))
    job_queue = PriorityQueue(maxsize=conf.LV30_MAX_QUEUE)
    coroutine_semaphore = Semaphore(workers_needed, loop=LOOP)

    def needs_sleep(self):
        return False 

    def min_level(self):
        return 30

    def max_level(self):
        return 100 

    def get_start_coords(self):
        return bounds.center

    def estimated_extra_accounts(self):
        return Account.estimated_extra_accounts(level30=True)

    def required_extra_accounts(self):
        return 0
    
    async def account_promotion(self):
        if self.player_level and self.player_level < 30:
            self.log.warning('{} is marked as Lv.30 while it is in fact Lv.{}. Moving it out of high-level captain pool', self.username, self.player_level)
            await sleep(1, loop=LOOP)
            await self.remove_account(flag='level1')

    @classmethod
    def add_job(self, pokemon):
        self.job_queue.put_nowait((pokemon.get('expire_timestamp',0), random(), pokemon))

    @classmethod
    async def launch(self, overseer):
        self.overseer = overseer
        self.lv30_captcha_queue = overseer.manager.lv30_captcha_queue()
        self.lv30_account_queue = overseer.manager.lv30_account_queue()
        if conf.MAP_WORKERS:
            self.lv30_worker_dict = overseer.manager.lv30_worker_dict()
        else:
            self.lv30_worker_dict = None
        self.lv30_account_dict = get_accounts30()
        overseer.add_accounts_to_queue(self.lv30_account_dict,
                self.lv30_captcha_queue,
                self.lv30_account_queue)
        try:
            await sleep(10)
            log.info("Couroutine launched.")
        
            # Initialize workers
            for x in range(self.workers_needed):
                try:
                    self.workers.append(Worker30(worker_no=x,
                        overseer=overseer,
                        captcha_queue=self.lv30_captcha_queue,
                        account_queue=self.lv30_account_queue,
                        worker_dict=self.lv30_worker_dict,
                        account_dict=self.lv30_account_dict))
                except Exception as e:
                    log.error("Worker initialization error: {}", e)
                    traceback.print_exc()
            log.info("Worker30 count: ({}/{})", len(self.workers), self.workers_needed)

            while True:
                try:
                    while not self.job_queue.empty():
                        job = self.job_queue.get()[2]
                        log.debug("Job: {}", job)

                        if job in ENCOUNTER_CACHE:
                            continue
            
                        await sleep(conf.LV30_ENCOUNTER_WAIT, loop=LOOP)
                        await self.coroutine_semaphore.acquire()
                        LOOP.create_task(self.try_point(job))
                except Exception as e:
                    log.warning("A wild error appeared in launcher loop: {}", e)
                await sleep(1)
        except CancelledError:
            log.info("Coroutine cancelled.")
            while not self.job_queue.empty():
                job = self.job_queue.get()[2]
                job['check_duplicate'] = True
                db_proc.add(job)
        except Exception as e:
            log.warning("A wild error appeared in launcher: {}", e)


    @classmethod
    async def try_point(self, job):
        try:
            encounter_only = HARDCORE_HYPERDRIVE
            if job in ENCOUNTER_CACHE:
                return
            point = (job['lat'], job['lon'])
            encounter_id = job['encounter_id']
            spawn_id = job['spawn_id']
            expire_timestamp = job['expire_timestamp']
            if time() >= expire_timestamp - 30.0:
                raise LateEncounterSkippedError("Insufficient time, {}s left"
                        .format(int(expire_timestamp - time())))
            spawn_time = spawns.spawn_timestamps.get(spawn_id, 0)
            point = randomize_point(point,amount=0.00003) # jitter around 3 meters
            skip_time = monotonic() + conf.GIVE_UP_KNOWN
            worker = await self.best_worker(point, skip_time)
            if job in ENCOUNTER_CACHE:
                return
            if not worker:
                raise RetriableEncounterSkippedError("Unavailable worker")
            async with worker.busy:
                if spawn_time:
                    worker.after_spawn = time() - spawn_time
                if conf.LV30_MAX_SPEED and not HARDCORE_HYPERDRIVE:
                    if await worker.sleep_travel_time(point, max_speed=conf.LV30_MAX_SPEED):
                        if job in ENCOUNTER_CACHE:
                            return
                ENCOUNTER_CACHE.remove(job['encounter_id'], job['spawn_id'])
                visit_result = await worker.visit(point,
                        encounter_id=encounter_id,
                        spawn_id=spawn_id,
                        encounter_only=encounter_only,
                        sighting=job)
                if visit_result == -1:
                    self.hash_burn += 1
                    await sleep(1.0, loop=LOOP)
                    point = randomize_point(point,amount=0.00001) # jitter around 3 meters
                    ENCOUNTER_CACHE.remove(job['encounter_id'], job['spawn_id'])
                    visit_result = await worker.visit(point,
                            encounter_id=encounter_id,
                            spawn_id=spawn_id,
                            encounter_only=encounter_only,
                            sighting=job)
                if visit_result:
                    if visit_result == -1:
                        if sb_detector:
                            sb_detector.add_encounter_miss(worker.account)
                        raise RetriableEncounterSkippedError("Pokemon not seen. Possibly shadow banned.")
                    else:
                        if not encounter_only:
                            self.visits += 1
                else:
                    raise RetriableEncounterSkippedError("Encounter request failed due to unknown error.")
        except CancelledError:
            raise
        except RetriableEncounterSkippedError as e:
            try:
                if 'retry' in job:
                    if job['retry'] > 1:
                        raise EncounterSkippedError('{} retry failures'.format(job['retry']))
                    else:
                        job['retry'] += 1 
                else:
                    job['retry'] = 1
                if self.overseer.running:
                    Worker30.add_job(job)
                    if worker:
                        log.info("Requeued encounter {} by {} for retry attemp #{}", encounter_id, worker.username, job['retry'])
                    else:
                        log.info("Requeued encounter {} for retry attemp #{}", encounter_id, job['retry'])
                else:
                    raise CancelledError("Overseer is no longer running")
            except Exception as e:
                self.skipped += 1
                ENCOUNTER_CACHE.add(job)
                job['check_duplicate'] = True
                db_proc.add(job)
                if worker:
                    username = worker.username
                else:
                    username = "worker"
                log.info("Skipping encounter {} by {} due to error: {}", encounter_id, username, e)
        except (LateEncounterSkippedError, EncounterSkippedError) as e:
            if isinstance(e, LateEncounterSkippedError):
                self.lates += 1
            self.skipped += 1
            ENCOUNTER_CACHE.add(job)
            job['check_duplicate'] = True
            db_proc.add(job)
            log.info("Skipping encounter {} due to error: {}", encounter_id, e)
        except Exception as e:
            log.error('An exception occurred in try_point: {}', e)
        finally:
            self.coroutine_semaphore.release()

    @classmethod
    async def best_worker(self, point, skip_time):
        while self.overseer.running:
            gen = (w for w in self.workers if not w.busy.locked())
            try:
                worker = next(gen)
                lowest_speed = worker.travel_speed(point)
            except StopIteration:
                lowest_speed = float('inf')
            for w in gen:
                speed = w.travel_speed(point)
                if speed < lowest_speed:
                    lowest_speed = speed
                    worker = w
            if worker:
                worker.speed = lowest_speed
                return worker
            if skip_time and monotonic() > skip_time:
                return None
            await sleep(conf.SEARCH_SLEEP, loop=LOOP)

class EncounterCache(SightingCache):
    """Simple cache for storing encountered sightings
    """
    def __contains__(self, raw_sighting):
        try:
            return (self.store[raw_sighting['encounter_id']] is not None)
        except KeyError:
            return False

    # Preloading from db
    def preload(self):
        with session_scope() as session:
            sightings = session.query(Sighting) \
                .join(Sighting.spawnpoint) \
                .filter(Sighting.expire_timestamp >= time()) \
                .filter(Sighting.atk_iv != None) \
                .filter(Spawnpoint.lat.between(bounds.south - 0.015, bounds.north + 0.015),
                        Spawnpoint.lon.between(bounds.west - 0.015, bounds.east + 0.015))

            sightings_lured = session.query(Sighting) \
                .filter(Sighting.spawn_id == 0) \
                .filter(Sighting.atk_iv != None) \
                .filter(Sighting.expire_timestamp >= time()) \
                .filter(Sighting.lat.between(bounds.south - 0.015, bounds.north + 0.015),
                        Sighting.lon.between(bounds.west - 0.015, bounds.east + 0.015))

            sightings = sightings.union(sightings_lured)

            for sighting in sightings:
                obj = {
                    'encounter_id': sighting.encounter_id,
                    'spawn_id': sighting.spawn_id,
                    'expire_timestamp': sighting.expire_timestamp,
                }
                self.add(obj)
            log.info("Preloaded {} encountered sightings", sightings.count())

ENCOUNTER_CACHE = EncounterCache()
