import sys

from queue import Queue
from threading import Thread
from time import sleep, time

from sqlalchemy.exc import IntegrityError

from . import db, spawns
from .shared import get_logger, LOOP

class DatabaseProcessor(Thread):

    def __init__(self):
        super().__init__()
        self.queue = Queue()
        self.log = get_logger('dbprocessor')
        self.running = True
        self.count = 0
        self._commit = False
        self.session = None

    def __len__(self):
        return self.queue.qsize()

    def stop(self):
        self.update_mysteries()
        self.running = False
        self.queue.put({'type': False})

    def add(self, obj):
        self.queue.put(obj)

    def run(self):
        session = db.Session()
        self.session = session
        LOOP.call_soon_threadsafe(self.commit)

        while self.running or not self.queue.empty():
            try:
                item = self.queue.get()
                item_type = item['type']

                if item_type == 'pokemon':
                    spawn_id = item['spawn_id']
                    if not item['inferred']:
                        db.add_spawnpoint(session, item)
                        spawns.updated_at[spawn_id] = int(time())
                    else:
                        # touch every 6 hours
                        if (spawn_id > 0 and (spawn_id not in spawns.updated_at or spawns.updated_at[spawn_id] < (time() - 21600))):
                            updated_at = db.touch_spawnpoint(session, spawn_id)
                            spawns.updated_at[spawn_id] = updated_at
                    db.add_sighting(session, item)
                    self.count += 1

                elif item_type == 'mystery':
                    db.add_mystery(session, item)
                    self.count += 1
                elif item_type == 'raid':
                    db.add_raid(session, item)
                elif item_type == 'fort':
                    db.add_fort_sighting(session, item)
                elif item_type == 'pokestop':
                    db.add_pokestop(session, item)
                elif item_type == 'target':
                    db.update_failures(session, item['spawn_id'], item['seen'])
                elif item_type == 'mystery-update':
                    db.update_mystery(session, item)
                elif item_type is False:
                    break
                self.log.debug('Item saved to db')
                if self._commit:
                    session.commit()
                    self._commit = False
            except IntegrityError as e:
                session.rollback()
                self.log.error('A wild {} appeared in the DB processor!: {}', e.__class__.__name__, e.args[0])
            except Exception as e:
                session.rollback()
                self.log.exception('A wild {} appeared in the DB processor!', e.__class__.__name__)
        try:
            session.commit()
        except Exception:
            pass
        session.close()

    def commit(self):
        self._commit = True
        if self.running:
            LOOP.call_later(1, self.commit)

    def update_mysteries(self):
       for key, times in db.MYSTERY_CACHE.items():
           first, last = times
           if last != first:
               encounter_id, spawn_id = key
               mystery = {
                   'type': 'mystery-update',
                   'spawn': spawn_id,
                   'encounter': encounter_id,
                   'first': first,
                   'last': last
               }
               self.add(mystery)

sys.modules[__name__] = DatabaseProcessor()
