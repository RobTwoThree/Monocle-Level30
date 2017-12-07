from logging import getLogger, LoggerAdapter
from concurrent.futures import ThreadPoolExecutor
from time import time
from asyncio import get_event_loop

from aiohttp import ClientSession
from aiopogo import json_dumps
from aiopogo.session import SESSIONS


LOOP = get_event_loop()


class SessionManager:
    @classmethod
    def get(cls):
        try:
            return cls._session
        except AttributeError:
            cls._session = ClientSession(connector=SESSIONS.get_connector(False),
                                         loop=LOOP,
                                         conn_timeout=5.0,
                                         read_timeout=30.0,
                                         connector_owner=False,
                                         raise_for_status=True,
                                         json_serialize=json_dumps)
            return cls._session

    @classmethod
    def close(cls):
        try:
            cls._session.close()
        except Exception:
            pass


class Message:
    def __init__(self, fmt, args):
        self.fmt = fmt
        self.args = args

    def __str__(self):
        return self.fmt.format(*self.args)


class StyleAdapter(LoggerAdapter):
    def __init__(self, logger, extra=None):
        super(StyleAdapter, self).__init__(logger, extra or {})

    def log(self, level, msg, *args, **kwargs):
        if self.isEnabledFor(level):
            msg, kwargs = self.process(msg, kwargs)
            self.logger._log(level, Message(msg, args), (), **kwargs)


def get_logger(name=None):
    return StyleAdapter(getLogger(name))


def call_later(delay, cb, *args):
    """Thread-safe wrapper for call_later"""
    try:
        return LOOP.call_soon_threadsafe(LOOP.call_later, delay, cb, *args)
    except RuntimeError:
        if not LOOP.is_closed():
            raise


def call_at(when, cb, *args):
    """Run call back at the unix time given"""
    delay = when - time()
    return call_later(delay, cb, *args)


async def run_threaded(cb, *args):
    with ThreadPoolExecutor(max_workers=1) as x:
        return await LOOP.run_in_executor(x, cb, *args)


class TtlCache:
    """Simple cache for storing Pokemon with unknown expiration times

    It's used in order not to make as many queries to the database.
    It schedules sightings to be removed an hour after being seen.
    """
    def __init__(self,ttl=300):
        self.store = {}
        self.ttl = ttl

    def __len__(self):
        return len(self.store)

    def add(self, key):
        now = time()
        self.store[key] = True 
        call_at(now + self.ttl, self.remove, key)

    def __contains__(self, key):
        return key in self.store

    def remove(self, key):
        if key in self.store:
            del self.store[key]

    def items(self):
        return self.store.items()
