import traceback
from math import ceil
from queue import PriorityQueue
from time import time, monotonic
from random import random
from asyncio import CancelledError, Semaphore, sleep
from sqlalchemy import desc
from sqlalchemy.orm import joinedload


from .db import Fort, FortSighting, GymDefender, Raid, session_scope, get_fort_internal_id, FORT_CACHE
from .utils import randomize_point
from .worker import Worker, UNIT
from .shared import LOOP, call_at, get_logger
from .accounts import Account
from . import bounds, sanitized as conf

log = get_logger("workerraider")

class GymNotFoundError(Exception):
    """Raised when gym is not found at the usual spot"""
    pass

class NothingSeenAtGymSpotError(Exception):
    """Raised when nothing is seen at the gym spot"""
    pass

class WorkerRaider(Worker):
    workers = [] 
    gyms = {}
    gym_scans = 0
    skipped = 0
    visits = 0
    hash_burn = 0
    workers_needed = 0
    job_queue = PriorityQueue()
    last_semaphore_value = workers_needed
    coroutine_semaphore = Semaphore(len(workers), loop=LOOP)

    def __init__(self, worker_no, overseer, captcha_queue, account_queue, worker_dict, account_dict, start_coords=None):
        super().__init__(worker_no, overseer, captcha_queue, account_queue, worker_dict, account_dict, start_coords=start_coords)
        self.scan_delayed = 0

    def needs_sleep(self):
        return False 

    def get_start_coords(self):
        return bounds.center

    def required_extra_accounts(self):
        return super().required_extra_accounts() + self.workers_needed

    @classmethod
    def preload(self):
        log.info("Preloading forts")
        with session_scope() as session:
            forts = session.query(Fort) \
                .options(joinedload(Fort.sightings)) \
                .filter(Fort.lat.between(bounds.south, bounds.north),
                        Fort.lon.between(bounds.west, bounds.east))
            try:
                for fort in forts:
                    if (fort.lat, fort.lon) not in bounds:
                        continue
                    obj = {
                        'id': fort.id,
                        'external_id': fort.external_id,
                        'lat': fort.lat,
                        'lon': fort.lon,
                        'name': fort.name,
                        'url': fort.url,
                        'last_modified': 0,
                        'updated': 0,
                    }
                    if len(fort.sightings) > 0:
                        sighting = fort.sightings[0]
                        obj['last_modified'] = sighting.last_modified
                        obj['updated'] = sighting.updated
                    self.add_gym(obj)
            except Exception as e:
                log.error("ERROR: {}", e)
            log.info("Loaded {} forts", self.job_queue.qsize())
    
    @classmethod
    def add_job(self, gym):
        self.job_queue.put_nowait((gym.get('updated', gym.get('last_modified', 0)), random(), gym))

    @classmethod
    def add_gym(self, gym):
        if gym['external_id'] in self.gyms:
            return
        self.gyms[gym['external_id']] = {'miss': 0}
        self.workers_needed = int(ceil(conf.RAIDERS_PER_GYM * len(self.gyms)))
        if len(self.workers) < self.workers_needed:
            try:
                self.workers.append(WorkerRaider(worker_no=len(self.workers),
                    overseer=self.overseer,
                    captcha_queue=self.overseer.captcha_queue,
                    account_queue=self.overseer.extra_queue,
                    worker_dict=self.overseer.worker_dict,
                    account_dict=self.overseer.account_dict))
            except Exception as e:
                log.error("WorkerRaider initialization error: {}", e)
                traceback.print_exc()
        self.add_job(gym)

    @classmethod
    def obliterate_gym(self, gym):
        external_id = gym['external_id']
        if external_id not in self.gyms:
            return
        with session_scope() as session:
            fort_id = get_fort_internal_id(session, external_id)
            if not fort_id:
                return
            session.query(GymDefender).filter(GymDefender.fort_id==fort_id).delete()
            session.query(Raid).filter(Raid.fort_id==fort_id).delete()
            session.query(FortSighting).filter(FortSighting.fort_id==fort_id).delete()
            session.query(Fort).filter(Fort.id==fort_id).delete()

            del self.gyms[external_id]
            FORT_CACHE.remove_gym(external_id)
            log.warning("Fort {} obliterated.", external_id)

    @classmethod
    async def launch(self, overseer):
        self.overseer = overseer
        self.preload()
        try:
            await sleep(5)
            log.info("Couroutine launched.")
        
            log.info("WorkerRaider count: ({}/{})", len(self.workers), self.workers_needed)

            while True:
                try:
                    while self.last_semaphore_value > 0 and self.last_semaphore_value == len(self.workers) and not self.job_queue.empty():
                        priority_job = self.job_queue.get()
                        updated = priority_job[0]
                        job = priority_job[2]
                        log.debug("Job: {}", job)

                        if (time() - updated) < 30:
                            await sleep(1)
                            self.add_job(job)
                            continue
                        await self.coroutine_semaphore.acquire()
                        LOOP.create_task(self.try_point(job))
                except CancelledError:
                    raise
                except Exception as e:
                    log.warning("A wild error appeared in launcher loop: {}", e)

                worker_count = len(self.workers)
                if self.last_semaphore_value != worker_count:
                    self.last_semaphore_value = worker_count
                    self.coroutine_semaphore = Semaphore(worker_count, loop=LOOP)
                    log.info("Semaphore updated with value {}", worker_count)
                await sleep(1)
        except CancelledError:
            log.info("Coroutine cancelled.")
        except Exception as e:
            log.warning("A wild error appeared in launcher: {}", e)

    @classmethod
    async def try_point(self, job):
        try:
            point = (job['lat'], job['lon'])
            fort_external_id = job['external_id']
            updated = job.get('updated', job.get('last_modified', 0))
            point = randomize_point(point,amount=0.00003) # jitter around 3 meters
            skip_time = monotonic() + (conf.SEARCH_SLEEP)
            worker = await self.best_worker(point, job, updated, skip_time)
            if not worker:
                return
            async with worker.busy:
                visit_result = await worker.visit(point,
                        gym=job)
                if visit_result == -1:
                    self.hash_burn += 1
                    await sleep(1.0, loop=LOOP)
                    point = randomize_point(point,amount=0.00001) # jitter around 3 meters
                    visit_result = await worker.visit(point,
                            gym=job)
                if visit_result:
                    if visit_result == -1:
                        miss = self.gyms[fort_external_id]['miss']
                        miss += 1
                        self.gyms[fort_external_id]['miss'] = miss
                        raise GymNotFoundError("Gym {} disappeared. Total misses: {}".format(fort_external_id, miss))
                    else:
                        if worker and worker.account and 'gym_nothing_seen' in worker.account:
                            del worker.account['gym_nothing_seen']
                        self.gyms[fort_external_id]['miss'] = 0
                        now = int(time())
                        worker.scan_delayed = now - updated
                        job['updated'] = now
                        self.visits += 1
                else:
                    if worker and worker.account:
                        username = worker.username
                        account_miss = worker.account.get('gym_nothing_seen', 0)
                        account_miss += 1
                        worker.account['gym_nothing_seen'] = account_miss
                    else:
                        username = None
                        account_miss = 1
                    raise NothingSeenAtGymSpotError("Nothing seen while scanning {} by {} for {} times.".format(fort_external_id, username, account_miss))
        except CancelledError:
            raise
        except (GymNotFoundError,NothingSeenAtGymSpotError) as e:
            self.skipped += 1
            if worker:
                worker.log.error('Gym visit error: {}', e)
            if isinstance(e, GymNotFoundError):
                miss = self.gyms[fort_external_id]['miss']
                if miss >= 10:
                    self.obliterate_gym(job)
            if isinstance(e, NothingSeenAtGymSpotError):
                if worker and worker.account:
                    account_miss = worker.account.get('gym_nothing_seen', 0)
                    await sleep(account_miss * 5, loop=LOOP)
        except Exception as e:
            self.skipped += 1
            log.exception('An exception occurred in try_point: {}', e)
        finally:
            if fort_external_id in self.gyms:
                if 'updated' in job:
                    job['updated'] += 5
                self.add_job(job)
            self.coroutine_semaphore.release()

    @classmethod
    async def best_worker(self, point, job, updated, skip_time):
        while self.overseer.running:
            gen = (w for w in self.workers if not w.busy.locked())
            worker = None
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
            time_diff = max(int(time() - updated), 0)
            speed_factor = (1.0 + (time_diff / 10))
            speed_limit = (conf.SPEED_LIMIT * speed_factor)
            if worker and lowest_speed < speed_limit:
                worker.speed = lowest_speed
                return worker
            if skip_time and monotonic() > skip_time:
                return None
            await sleep(conf.SEARCH_SLEEP, loop=LOOP)
