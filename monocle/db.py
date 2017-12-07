from datetime import datetime
from collections import OrderedDict
from contextlib import contextmanager
from enum import Enum
from time import time, mktime
from datetime import datetime

from sqlalchemy import Column, Boolean, Integer, String, Float, SmallInteger, \
        BigInteger, ForeignKey, Index, UniqueConstraint, \
        create_engine, cast, func, desc, asc, desc, and_, exists
from sqlalchemy.orm import sessionmaker, relationship, eagerload, foreign, remote
from sqlalchemy.types import TypeDecorator, Numeric, Text, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base

from . import bounds, spawns, db_proc, sanitized as conf
from .utils import time_until_time, dump_pickle, load_pickle
from .shared import call_at, get_logger

try:
    assert conf.LAST_MIGRATION < time()
except AssertionError:
    raise ValueError('LAST_MIGRATION must be a timestamp from the past.')

log = get_logger(__name__)

if conf.DB_ENGINE.startswith('mysql'):
    from sqlalchemy.dialects.mysql import TINYINT, MEDIUMINT, BIGINT, DOUBLE

    TINY_TYPE = TINYINT(unsigned=True)          # 0 to 255
    MEDIUM_TYPE = MEDIUMINT(unsigned=True)      # 0 to 4294967295
    UNSIGNED_HUGE_TYPE = BIGINT(unsigned=True)           # 0 to 18446744073709551615
    HUGE_TYPE = BigInteger
    PRIMARY_HUGE_TYPE = HUGE_TYPE 
    FLOAT_TYPE = DOUBLE(precision=17, scale=14, asdecimal=False)
elif conf.DB_ENGINE.startswith('postgres'):
    from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION

    class NumInt(TypeDecorator):
        '''Modify Numeric type for integers'''
        impl = Numeric

        def process_bind_param(self, value, dialect):
            return int(value)

        def process_result_value(self, value, dialect):
            return int(value)

        @property
        def python_type(self):
            return int

    TINY_TYPE = SmallInteger                    # -32768 to 32767
    MEDIUM_TYPE = Integer                       # -2147483648 to 2147483647
    UNSIGNED_HUGE_TYPE = NumInt(precision=20, scale=0)   # up to 20 digits
    HUGE_TYPE = BigInteger
    PRIMARY_HUGE_TYPE = HUGE_TYPE 
    FLOAT_TYPE = DOUBLE_PRECISION(asdecimal=False)
else:
    class TextInt(TypeDecorator):
        '''Modify Text type for integers'''
        impl = Text

        def process_bind_param(self, value, dialect):
            return str(value)

        def process_result_value(self, value, dialect):
            return int(value)

    TINY_TYPE = SmallInteger
    MEDIUM_TYPE = Integer
    UNSIGNED_HUGE_TYPE = TextInt
    HUGE_TYPE = Integer
    PRIMARY_HUGE_TYPE = HUGE_TYPE 
    FLOAT_TYPE = Float(asdecimal=False)


class Team(Enum):
    none = 0
    mystic = 1
    valor = 2
    instict = 3


def combine_key(sighting):
    return sighting['encounter_id'], sighting['spawn_id']


class SightingCache:
    """Simple cache for storing actual sightings

    It's used in order not to make as many queries to the database.
    It schedules sightings to be removed as soon as they expire.
    """
    def __init__(self):
        self.store = {}
        self.spawn_ids = {}

    def __len__(self):
        return len(self.store)

    def add(self, sighting):
        self.store[sighting['encounter_id']] = sighting['expire_timestamp']
        self.spawn_ids[sighting['spawn_id']] = True
        call_at(sighting['expire_timestamp'] + 60, self.remove, sighting['encounter_id'], sighting['spawn_id'])

    def remove(self, encounter_id, spawn_id):
        if encounter_id in  self.store:
            del self.store[encounter_id]
        if spawn_id in self.spawn_ids:
            del self.spawn_ids[spawn_id]

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
                .filter(Spawnpoint.lat.between(bounds.south, bounds.north),
                        Spawnpoint.lon.between(bounds.west, bounds.east))

            sightings_lured = session.query(Sighting) \
                .filter(Sighting.spawn_id == 0) \
                .filter(Sighting.expire_timestamp >= time()) \
                .filter(Sighting.lat.between(bounds.south, bounds.north),
                        Sighting.lon.between(bounds.west, bounds.east))

            sightings = sightings.union(sightings_lured)
            for sighting in sightings:
                if (sighting.lat, sighting.lon) not in bounds:
                    continue
                obj = {
                    'encounter_id': sighting.encounter_id,
                    'spawn_id': sighting.spawn_id,
                    'expire_timestamp': sighting.expire_timestamp,
                }
                self.add(obj)
            log.info("Preloaded {} sightings", len(self))


class MysteryCache:
    """Simple cache for storing Pokemon with unknown expiration times

    It's used in order not to make as many queries to the database.
    It schedules sightings to be removed an hour after being seen.
    """
    def __init__(self):
        self.store = {}

    def __len__(self):
        return len(self.store)

    def add(self, sighting):
        key = combine_key(sighting)
        self.store[key] = [sighting['seen']] * 2
        call_at(sighting['seen'] + 3510, self.remove, key)

    def __contains__(self, raw_sighting):
        key = combine_key(raw_sighting)
        try:
            first, last = self.store[key]
        except (KeyError, TypeError):
            return False
        new_time = raw_sighting['seen']
        if new_time > last:
            self.store[key][1] = new_time
        return True

    def remove(self, key):
        first, last = self.store[key]
        del self.store[key]
        if last != first:
            encounter_id, spawn_id = key
            db_proc.add({
                'type': 'mystery-update',
                'spawn': spawn_id,
                'encounter': encounter_id,
                'first': first,
                'last': last
            })

    def items(self):
        return self.store.items()


class RaidCache:
    """Simple cache for storing actual raids

    It's used in order not to make as many queries to the database.
    It schedules raids to be removed as soon as they expire.
    """
    def __init__(self):
        self.store = {}

    def __len__(self):
        return len(self.store)

    def add(self, raid):
        self.store[raid['fort_external_id']] = raid
        call_at(raid['time_end'], self.remove, raid['fort_external_id'])

    def remove(self, cache_id):
        try:
            del self.store[cache_id]
        except KeyError:
            pass

    def __contains__(self, raw_fort):
        try:
            raid = self.store[raw_fort.id]
            if raw_fort.raid_info.raid_pokemon:
                return (
                    raid['time_end'] > raw_fort.raid_info.raid_end_ms // 1000 - 2 and
                    raid['time_end'] < raw_fort.raid_info.raid_end_ms // 1000 + 2 and
                    raid['pokemon_id'] == raw_fort.raid_info.raid_pokemon.pokemon_id)
            return True
        except KeyError:
            return False

    # Preloading from db
    def preload(self):
        with session_scope() as session:
            raids = session.query(Raid) \
                .options(eagerload(Raid.fort)) \
                .join(Fort, Fort.id == Raid.fort_id) \
                .filter(Raid.time_end > time()) \
                .filter(Fort.lat.between(bounds.south, bounds.north),
                        Fort.lon.between(bounds.west, bounds.east))
            for raid in raids:
                fort = raid.fort
                if (fort.lat, fort.lon) not in bounds:
                    continue
                r = {}
                r['fort_external_id'] = fort.external_id
                r['time_end'] = raid.time_end
                r['pokemon_id'] = raid.pokemon_id
                self.add(r)
            log.info("Preloaded {} raids", len(self))
            


class FortCache:
    """Simple cache for storing fort sightings"""
    def __init__(self):
        self.gyms = {}
        self.internal_ids = {}
        self.gym_names = {}
        self.pokestops = {}
        self.pokestop_names = {}
        self.class_version = 2.1

    def __len__(self):
        return len(self.gyms)

    def add(self, fort):
        self.gyms[fort['external_id']] = fort['last_modified']

    def remove_gym(self, external_id):
        if external_id in self.gyms:
            del self.gyms[external_id]
        if external_id in self.internal_ids:
            del self.internal_ids[external_id]
        if external_id in self.gym_names:
            del self.gym_names[external_id]

    def __contains__(self, sighting):
        try:
            return self.gyms[sighting.id] == sighting.last_modified_timestamp_ms // 1000
        except KeyError:
            return False

    def pickle(self):
        state = self.__dict__.copy()
        state['db_hash'] = spawns.db_hash
        state['bounds_hash'] = hash(bounds)
        dump_pickle('forts', state)

    # Preloading from db
    def preload(self):
        with session_scope() as session:
            fort_sightings = session.query(FortSighting) \
                .join(FortSighting.fort) \
                .filter(Fort.lat.between(bounds.south, bounds.north),
                        Fort.lon.between(bounds.west, bounds.east))
            for fort_sighting in fort_sightings:
                if (fort_sighting.fort.lat, fort_sighting.fort.lon) not in bounds:
                    continue
                fort = fort_sighting.fort
                external_id = fort.external_id
                self.internal_ids[external_id] = fort_sighting.fort_id
                if fort.name:
                    self.gym_names[external_id] = (fort.name, fort.url)
                obj = {
                    'external_id': fort_sighting.fort.external_id,
                    'last_modified': fort_sighting.last_modified,
                }
                self.add(obj)
            log.info("Preloaded {} fort_sightings ", len(self))

            pokestops = session.query(Pokestop) \
                .filter(Pokestop.lat.between(bounds.south, bounds.north),
                        Pokestop.lon.between(bounds.west, bounds.east))
            for pokestop in pokestops:
                if (pokestop.lat, pokestop.lon) not in bounds:
                    continue
                self.pokestops[pokestop.external_id] = (pokestop.lat, pokestop.lon)
                if pokestop.name:
                    self.pokestop_names[pokestop.external_id] = pokestop.name
            log.info("Preloaded {} pokestops", len(self.pokestop_names))


SIGHTING_CACHE = SightingCache()
MYSTERY_CACHE = MysteryCache()
FORT_CACHE = FortCache()
RAID_CACHE = RaidCache()

Base = declarative_base()

_engine = create_engine(conf.DB_ENGINE, pool_size=conf.DB_POOL_SIZE, max_overflow=conf.DB_MAX_OVERFLOW, pool_recycle=conf.DB_POOL_RECYCLE, isolation_level='READ_UNCOMMITTED')
Session = sessionmaker(bind=_engine)
DB_TYPE = _engine.name


if conf.REPORT_SINCE:
    SINCE_TIME = mktime(conf.REPORT_SINCE.timetuple())
    SINCE_QUERY = 'WHERE expire_timestamp > {}'.format(SINCE_TIME)
else:
    SINCE_QUERY = ''


class Common(Base):
    __tablename__ = 'common'

    id = Column(Integer, primary_key=True)
    key = Column(String(32), index=True, nullable=False)
    val = Column(String(64), nullable=True)


class Sighting(Base):
    __tablename__ = 'sightings'

    id = Column(PRIMARY_HUGE_TYPE, primary_key=True)
    pokemon_id = Column(SmallInteger)
    spawn_id = Column(BigInteger)
    expire_timestamp = Column(Integer, index=True)
    encounter_id = Column(UNSIGNED_HUGE_TYPE, index=True)
    lat = Column(FLOAT_TYPE)
    lon = Column(FLOAT_TYPE)
    atk_iv = Column(TINY_TYPE)
    def_iv = Column(TINY_TYPE)
    sta_iv = Column(TINY_TYPE)
    move_1 = Column(SmallInteger)
    move_2 = Column(SmallInteger)
    gender = Column(SmallInteger)
    form = Column(SmallInteger)
    cp = Column(SmallInteger)
    level = Column(SmallInteger)
    updated = Column(Integer,default=time,onupdate=time)

    spawnpoint = relationship("Spawnpoint",
            uselist=False,
            primaryjoin="foreign(Sighting.spawn_id)==remote(Spawnpoint.spawn_id)",
            backref="sightings")

    __table_args__ = (
        UniqueConstraint(
            'encounter_id',
            'expire_timestamp',
            name='timestamp_encounter_id_unique'
        ),
    )

class Raid(Base):
    __tablename__ = 'raids'

    id = Column(Integer, primary_key=True)
    external_id = Column(BigInteger, unique=True)
    fort_id = Column(Integer, ForeignKey('forts.id'))
    level = Column(TINY_TYPE)
    pokemon_id = Column(SmallInteger)
    move_1 = Column(SmallInteger)
    move_2 = Column(SmallInteger)
    time_spawn = Column(Integer, index=True)
    time_battle = Column(Integer)
    time_end = Column(Integer)
    cp = Column(Integer)


class Mystery(Base):
    __tablename__ = 'mystery_sightings'

    id = Column(PRIMARY_HUGE_TYPE, primary_key=True)
    pokemon_id = Column(SmallInteger)
    spawn_id = Column(BigInteger, index=True)
    encounter_id = Column(UNSIGNED_HUGE_TYPE, index=True)
    lat = Column(FLOAT_TYPE)
    lon = Column(FLOAT_TYPE)
    first_seen = Column(Integer, index=True)
    first_seconds = Column(SmallInteger)
    last_seconds = Column(SmallInteger)
    seen_range = Column(SmallInteger)
    atk_iv = Column(TINY_TYPE)
    def_iv = Column(TINY_TYPE)
    sta_iv = Column(TINY_TYPE)
    move_1 = Column(SmallInteger)
    move_2 = Column(SmallInteger)
    gender = Column(SmallInteger)
    form = Column(SmallInteger)
    cp = Column(SmallInteger)
    level = Column(SmallInteger)

    __table_args__ = (
        UniqueConstraint(
            'encounter_id',
            'spawn_id',
            name='unique_encounter'
        ),
    )


class Spawnpoint(Base):
    __tablename__ = 'spawnpoints'

    id = Column(Integer, primary_key=True)
    spawn_id = Column(BigInteger, unique=True, index=True)
    despawn_time = Column(SmallInteger, index=True)
    lat = Column(FLOAT_TYPE)
    lon = Column(FLOAT_TYPE)
    updated = Column(Integer, index=True)
    duration = Column(TINY_TYPE)
    failures = Column(TINY_TYPE)

    __table_args__ = (
        Index('ix_coords_sp', "lat", "lon"),
    )


class Fort(Base):
    __tablename__ = 'forts'

    id = Column(Integer, primary_key=True)
    external_id = Column(String(35), unique=True)
    lat = Column(FLOAT_TYPE)
    lon = Column(FLOAT_TYPE)
    name = Column(String(128))
    url = Column(String(200))

    sightings = relationship(
        'FortSighting',
        backref='fort',
        order_by='FortSighting.last_modified'
    )

    raids = relationship(
        'Raid',
        backref='fort',
        order_by='Raid.time_end'
    )

    gym_defenders = relationship(
        'GymDefender',
        backref='fort',
        order_by='GymDefender.id',
        cascade="save-update, merge, delete"
    )

    __table_args__ = (
        Index('ix_coords', "lat", "lon"),
    )

class FortSighting(Base):
    __tablename__ = 'fort_sightings'

    id = Column(PRIMARY_HUGE_TYPE, primary_key=True)
    fort_id = Column(Integer, ForeignKey('forts.id'))
    last_modified = Column(Integer, index=True)
    team = Column(TINY_TYPE)
    guard_pokemon_id = Column(SmallInteger)
    slots_available = Column(SmallInteger)
    is_in_battle = Column(Boolean, default=False)
    updated = Column(Integer,default=time,onupdate=time)

    __table_args__ = (
        UniqueConstraint(
            'fort_id',
            'last_modified',
            name='fort_id_last_modified_unique'
        ),
    )

class GymDefender(Base):
    __tablename__ = 'gym_defenders'

    id = Column(PRIMARY_HUGE_TYPE, primary_key=True)
    fort_id = Column(Integer, ForeignKey('forts.id', onupdate="CASCADE", ondelete="CASCADE"), nullable=False, index=True)
    external_id = Column(UNSIGNED_HUGE_TYPE, nullable=False)
    pokemon_id = Column(SmallInteger)
    team = Column(TINY_TYPE)
    owner_name = Column(String(128))
    nickname = Column(String(128))
    cp = Column(Integer)
    stamina = Column(Integer)
    stamina_max = Column(Integer)
    atk_iv = Column(SmallInteger)
    def_iv = Column(SmallInteger)
    sta_iv = Column(SmallInteger)
    move_1 = Column(SmallInteger)
    move_2 = Column(SmallInteger)
    last_modified = Column(Integer)
    battles_attacked = Column(Integer)
    battles_defended = Column(Integer)
    num_upgrades = Column(SmallInteger)
    created = Column(Integer, index=True)

class Pokestop(Base):
    __tablename__ = 'pokestops'

    id = Column(Integer, primary_key=True)
    external_id = Column(String(35), unique=True)
    lat = Column(FLOAT_TYPE, index=True)
    lon = Column(FLOAT_TYPE, index=True)
    name = Column(String(128))
    url = Column(String(200))
    updated = Column(Integer,default=time,onupdate=time)


@contextmanager
def session_scope(autoflush=False):
    """Provide a transactional scope around a series of operations."""
    session = Session(autoflush=autoflush)
    try:
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()

def get_common(session, key, lock=False):
    common = session.query(Common).filter(Common.key==key)
    if lock:
        common = common.with_lockmode("update")
    common = common.first()
    if not common:
        common = Common()
        common.key = key
        session.add(common)
        session.commit()
    return common



def add_sighting(session, pokemon):
    if pokemon['spawn_id'] == 0 or pokemon.get('check_duplicate'):
        sighting = session.query(Sighting) \
                .filter(Sighting.encounter_id==pokemon['encounter_id']) \
                .first()
    elif not conf.KEEP_SPAWNPOINT_HISTORY:
        sighting = session.query(Sighting) \
                .filter(Sighting.spawn_id==pokemon['spawn_id']) \
                .order_by(desc(Sighting.id)) \
                .first()
    else:
        sighting = None

    if not sighting:
        sighting = Sighting()

    sighting.pokemon_id = pokemon['pokemon_id']
    sighting.spawn_id = pokemon['spawn_id']
    sighting.encounter_id = pokemon['encounter_id']
    sighting.expire_timestamp = pokemon['expire_timestamp']
    sighting.lat = pokemon['lat']
    sighting.lon = pokemon['lon']
    sighting.atk_iv = pokemon.get('individual_attack')
    sighting.def_iv = pokemon.get('individual_defense')
    sighting.sta_iv = pokemon.get('individual_stamina')
    sighting.move_1 = pokemon.get('move_1')
    sighting.move_2 = pokemon.get('move_2')
    sighting.gender = pokemon.get('gender', 0)
    sighting.form = pokemon.get('form', 0)
    sighting.cp = pokemon.get('cp')
    sighting.level = pokemon.get('level')

    session.merge(sighting)

    # Reset failures to 0 if needed
    spawn_id = pokemon['spawn_id']
    failures = spawns.failures.get(spawn_id, 0)
    if failures > 0:
        spawns.failures[spawn_id] = 0
        spawnpoint = session.query(Spawnpoint) \
            .filter(Spawnpoint.spawn_id == spawn_id) \
            .first()
        if spawnpoint:
            spawnpoint.failures = 0


def add_gym_defenders(session, fort_internal_id, gym_defenders, raw_fort):
        
    session.query(GymDefender).filter(GymDefender.fort_id==fort_internal_id).delete()

    for gym_defender in gym_defenders:
        obj = GymDefender(
            fort_id=fort_internal_id,
            external_id=gym_defender['external_id'],
            pokemon_id=gym_defender['pokemon_id'],
            owner_name=gym_defender['owner_name'],
            nickname=gym_defender['nickname'],
            cp=gym_defender['cp'],
            stamina=gym_defender['stamina'],
            stamina_max=gym_defender['stamina_max'],
            atk_iv=gym_defender['atk_iv'],
            def_iv=gym_defender['def_iv'],
            sta_iv=gym_defender['sta_iv'],
            move_1=gym_defender['move_1'],
            move_2=gym_defender['move_2'],
            battles_attacked=gym_defender['battles_attacked'],
            battles_defended=gym_defender['battles_defended'],
            num_upgrades=gym_defender['num_upgrades'],
            created=round(time()),
        )
        team = raw_fort.get('team')
        if team is not None:
            obj.team = team
        last_modified = raw_fort.get('last_modified')
        if last_modified is not None:
            obj.last_modified = last_modified
        session.add(obj)



def add_spawnpoint(session, pokemon):
    # Check if the same entry already exists
    spawn_id = pokemon['spawn_id']
    new_time = pokemon['expire_timestamp'] % 3600
    try:
        if new_time == spawns.despawn_times[spawn_id]:
            return
    except KeyError:
        pass
    existing = session.query(Spawnpoint) \
        .filter(Spawnpoint.spawn_id == spawn_id) \
        .first()
    now = round(time())
    point = pokemon['lat'], pokemon['lon']
    spawns.add_known(spawn_id, new_time, point)
    if existing:
        existing.updated = now
        existing.failures = 0

        if (existing.despawn_time is None or
                existing.updated < conf.LAST_MIGRATION):
            widest = get_widest_range(session, spawn_id)
            if widest and widest > 1800:
                existing.duration = 60
        elif new_time == existing.despawn_time:
            return

        existing.despawn_time = new_time
    else:
        widest = get_widest_range(session, spawn_id)

        duration = 60 if widest and widest > 1800 else None

        session.add(Spawnpoint(
            spawn_id=spawn_id,
            despawn_time=new_time,
            lat=pokemon['lat'],
            lon=pokemon['lon'],
            updated=now,
            duration=duration,
            failures=0
        ))


def touch_spawnpoint(session, spawn_id):
    if spawn_id in spawns.internal_ids: 
        internal_id = spawns.internal_ids[spawn_id]
    else:
        internal_id = session.query(Spawnpoint.id) \
            .filter(Spawnpoint.spawn_id == spawn_id) \
            .scalar()
        spawns.internal_ids[spawn_id] = internal_id
    now = int(time())
    spawnpoint = session.query(Spawnpoint) \
        .filter(Spawnpoint.id == internal_id) \
        .first()
    if spawnpoint:
        spawnpoint.updated = now
    return now


def add_mystery_spawnpoint(session, pokemon):
    # Check if the same entry already exists
    spawn_id = pokemon['spawn_id']
    point = pokemon['lat'], pokemon['lon']
    if point in spawns.unknown or session.query(exists().where(
            Spawnpoint.spawn_id == spawn_id)).scalar():
        return

    session.add(Spawnpoint(
        spawn_id=spawn_id,
        despawn_time=None,
        lat=pokemon['lat'],
        lon=pokemon['lon'],
        updated=0,
        duration=None,
        failures=0
    ))

    if point in bounds:
        spawns.add_unknown(point)


def add_mystery(session, pokemon):
    add_mystery_spawnpoint(session, pokemon)
    existing = session.query(Mystery) \
        .filter(Mystery.encounter_id == pokemon['encounter_id']) \
        .filter(Mystery.spawn_id == pokemon['spawn_id']) \
        .first()
    if existing:
        key = combine_key(pokemon)
        MYSTERY_CACHE.store[key] = [existing.first_seen, pokemon['seen']]
        return
    seconds = pokemon['seen'] % 3600
    obj = Mystery(
        pokemon_id=pokemon['pokemon_id'],
        spawn_id=pokemon['spawn_id'],
        encounter_id=pokemon['encounter_id'],
        lat=pokemon['lat'],
        lon=pokemon['lon'],
        first_seen=pokemon['seen'],
        first_seconds=seconds,
        last_seconds=seconds,
        seen_range=0,
        atk_iv=pokemon.get('individual_attack'),
        def_iv=pokemon.get('individual_defense'),
        sta_iv=pokemon.get('individual_stamina'),
        move_1=pokemon.get('move_1'),
        move_2=pokemon.get('move_2'),
        gender=pokemon.get('gender', 0),
        form=pokemon.get('form', 0),
        cp=pokemon.get('cp'),
        level=pokemon.get('level')
    )
    session.add(obj)

def get_fort_internal_id(session, external_id):
    if external_id in FORT_CACHE.internal_ids and FORT_CACHE.internal_ids[external_id]:
        internal_id = FORT_CACHE.internal_ids[external_id]
    else:
        internal_id = session.query(Fort.id) \
            .filter(Fort.external_id == external_id) \
            .scalar()
        FORT_CACHE.internal_ids[external_id] = internal_id 
    return internal_id

def add_fort_sighting(session, raw_fort):
    # Check if fort exists
    external_id = raw_fort['external_id']
    internal_id = get_fort_internal_id(session, external_id)

    fort_updated = False

    if not internal_id:
        fort = Fort(
            external_id=raw_fort['external_id'],
            lat=raw_fort['lat'],
            lon=raw_fort['lon'],
            name=raw_fort.get('name'),
            url=raw_fort.get('url'),
        )
        session.add(fort)
        session.flush()
        internal_id = fort.id
        FORT_CACHE.internal_ids[external_id] = internal_id 
        fort_updated = True

    has_fort_name = ('name' in raw_fort and raw_fort['name'])

    if external_id not in FORT_CACHE.gym_names and has_fort_name:
        session.query(Fort) \
                .filter(Fort.id == internal_id) \
                .update({
                    'name': raw_fort['name'],
                    'url': raw_fort['url']})
        fort_updated = True

    if (has_fort_name and
            (fort_updated or
                external_id not in FORT_CACHE.gym_names or
                FORT_CACHE.gym_names[external_id] == True)):
        FORT_CACHE.gym_names[external_id] = (raw_fort['name'], raw_fort['url']) 
    
    if 'gym_defenders' in raw_fort and len(raw_fort['gym_defenders']) > 0:
        add_gym_defenders(session, internal_id, raw_fort['gym_defenders'], raw_fort)

    if conf.KEEP_GYM_HISTORY:
        fort_sighting = None
    else:
        fort_sighting = session.query(FortSighting) \
                .filter(FortSighting.fort_id==internal_id) \
                .order_by(desc(FortSighting.id)) \
                .first()

    if not fort_sighting:
        fort_sighting = FortSighting()
    
    fort_sighting.fort_id = internal_id 
    fort_sighting.team = raw_fort['team']
    fort_sighting.guard_pokemon_id = raw_fort['guard_pokemon_id']
    fort_sighting.last_modified = raw_fort['last_modified']
    fort_sighting.slots_available = raw_fort['slots_available']
    fort_sighting.is_in_battle = raw_fort['is_in_battle']
    fort_sighting.updated = int(time())

    session.merge(fort_sighting)


def add_raid(session, raw_raid):
    fort_external_id = raw_raid['fort_external_id']
    fort_id = get_fort_internal_id(session, fort_external_id)

    raid = session.query(Raid) \
        .filter(Raid.external_id == raw_raid['external_id']) \
        .first()
    if raid:
        if raid.pokemon_id == 0 and raw_raid['pokemon_id'] != 0:
            raid.pokemon_id = raw_raid['pokemon_id']
            raid.cp = raw_raid['cp']
            raid.move_1 = raw_raid['move_1']
            raid.move_2 = raw_raid['move_2']
            session.merge(raid)
            touch_fort_sighting(session, fort_id)
        return

    if fort_id:
        if conf.KEEP_GYM_HISTORY:
            raid = None
        else:
            raid = session.query(Raid) \
                    .filter(Raid.fort_id==fort_id) \
                    .order_by(desc(Raid.id)) \
                    .first()

        if not raid:
            raid = Raid()
    
        raid.external_id = raw_raid['external_id']
        raid.fort_id = fort_id
        raid.level = raw_raid['level']
        raid.pokemon_id = raw_raid['pokemon_id']
        raid.time_spawn = raw_raid['time_spawn']
        raid.time_battle = raw_raid['time_battle']
        raid.time_end = raw_raid['time_end']
        raid.cp = raw_raid['cp']
        raid.move_1 = raw_raid['move_1']
        raid.move_2 = raw_raid['move_2']

        session.merge(raid)
        touch_fort_sighting(session, fort_id)

        
def touch_fort_sighting(session, fort_id):
    fort_sighting = session.query(FortSighting) \
            .filter(FortSighting.fort_id==fort_id) \
            .order_by(desc(FortSighting.last_modified)) \
            .first()
    if fort_sighting:
        fort_sighting.updated = int(time())


def add_pokestop(session, raw_pokestop):
    pokestop_id = raw_pokestop['external_id']

    if session.query(exists().where(
            Pokestop.external_id == pokestop_id)).scalar():
        FORT_CACHE.pokestops[pokestop_id] = (raw_pokestop['lat'], raw_pokestop['lon'])

        if pokestop_id in FORT_CACHE.pokestop_names:
            return
        elif raw_pokestop['name'] is None:
            return 

    pokestop = session.query(Pokestop) \
        .filter(Pokestop.external_id == pokestop_id) \
        .first()

    if not pokestop:
        pokestop = Pokestop(
            external_id=pokestop_id,
            lat=raw_pokestop['lat'],
            lon=raw_pokestop['lon'],
            name=raw_pokestop['name'],
            url=raw_pokestop['url'],
        )
    else:
        pokestop.name = raw_pokestop['name']
        pokestop.url = raw_pokestop['url']

    session.add(pokestop)

    FORT_CACHE.pokestops[pokestop_id] = (raw_pokestop['lat'], raw_pokestop['lon'])
    if raw_pokestop['name'] is not None:
        FORT_CACHE.pokestop_names[pokestop_id] = raw_pokestop['name']


def update_failures(session, spawn_id, success, allowed=conf.FAILURES_ALLOWED):
    spawnpoint = session.query(Spawnpoint) \
        .filter(Spawnpoint.spawn_id == spawn_id) \
        .first()
    if not spawnpoint:
        return
    try:
        if success:
            spawnpoint.failures = 0
        elif spawnpoint.failures >= allowed:
            if spawnpoint.duration == 60:
                spawnpoint.duration = None
                spawnpoint.failures = 0
                log.warning('{} consecutive failures on {}, no longer treating as an hour spawn.', allowed + 1, spawn_id)
            elif conf.SB_DETECTOR:
                session.delete(spawnpoint)
                spawns.remove_known(spawn_id)
                log.warning('{} consecutive failures on {}, deleted.', allowed + 1, spawn_id)
                return
            else:
                spawnpoint.updated = 0
                spawnpoint.failures = 0
                spawns.remove_known(spawn_id)
                log.warning('{} consecutive failures on {}, will treat as an unknown from now on.', allowed + 1, spawn_id)
                return
        else:
            spawnpoint.failures += 1
        spawns.failures[spawn_id] = spawnpoint.failures
    except TypeError:
        spawnpoint.failures = 1
        spawns.failures[spawn_id] = spawnpoint.failures


def update_mystery(session, mystery):
    encounter = session.query(Mystery) \
                .filter(Mystery.spawn_id == mystery['spawn']) \
                .filter(Mystery.encounter_id == mystery['encounter']) \
                .first()
    if not encounter:
        return
    hour = encounter.first_seen - (encounter.first_seen % 3600)
    encounter.last_seconds = mystery['last'] - hour
    encounter.seen_range = mystery['last'] - mystery['first']


def get_pokestops(session):
    return session.query(Pokestop).all()


def _get_forts_sqlite(session):
    # SQLite version is sloooooow compared to MySQL
    return session.execute('''
        SELECT
            fs.fort_id,
            fs.id,
            fs.team,
            fs.guard_pokemon_id,
            fs.last_modified,
            f.lat,
            f.lon,
            f.name,
            fs.slots_available
        FROM fort_sightings fs
        JOIN forts f ON f.id=fs.fort_id
        WHERE fs.fort_id || '-' || fs.last_modified IN (
            SELECT fort_id || '-' || MAX(last_modified)
            FROM fort_sightings
            GROUP BY fort_id
        )
    ''').fetchall()


def _get_forts(session):
    return session.execute('''
        SELECT
            fs.fort_id,
            fs.id,
            fs.team,
            fs.guard_pokemon_id,
            fs.last_modified,
            f.lat,
            f.lon,
            f.name,
            fs.slots_available
        FROM fort_sightings fs
        JOIN forts f ON f.id=fs.fort_id
        WHERE (fs.fort_id, fs.last_modified) IN (
            SELECT fort_id, MAX(last_modified)
            FROM fort_sightings
            GROUP BY fort_id
        )
    ''').fetchall()

get_forts = _get_forts_sqlite if DB_TYPE == 'sqlite' else _get_forts


def get_session_stats(session):
    query = session.query(func.min(Sighting.expire_timestamp),
        func.max(Sighting.expire_timestamp))
    if conf.REPORT_SINCE:
        query = query.filter(Sighting.expire_timestamp > SINCE_TIME)
    min_max_result = query.one()
    length_hours = (min_max_result[1] - min_max_result[0]) // 3600
    if length_hours == 0:
        length_hours = 1
    # Convert to datetime
    return {
        'start': datetime.fromtimestamp(min_max_result[0]),
        'end': datetime.fromtimestamp(min_max_result[1]),
        'length_hours': length_hours
    }


def get_first_last(session, spawn_id):
    return session.query(func.min(Mystery.first_seconds), func.max(Mystery.last_seconds)) \
        .filter(Mystery.spawn_id == spawn_id) \
        .filter(Mystery.first_seen > conf.LAST_MIGRATION) \
        .first()


def get_widest_range(session, spawn_id):
    return session.query(func.max(Mystery.seen_range)) \
        .filter(Mystery.spawn_id == spawn_id) \
        .filter(Mystery.first_seen > conf.LAST_MIGRATION) \
        .scalar()


def estimate_remaining_time(session, spawn_id, seen):
    first, last = get_first_last(session, spawn_id)

    if not first:
        return 90, 1800

    if seen > last:
        last = seen
    elif seen < first:
        first = seen

    if last - first > 1710:
        estimates = [
            time_until_time(x, seen)
            for x in (first + 90, last + 90, first + 1800, last + 1800)]
        return min(estimates), max(estimates)

    soonest = last + 90
    latest = first + 1800
    return time_until_time(soonest, seen), time_until_time(latest, seen)


def get_punch_card(session):
    query = session.query(cast(Sighting.expire_timestamp / 300, Integer).label('ts_date'), func.count('ts_date')) \
        .group_by('ts_date') \
        .order_by('ts_date')
    if conf.REPORT_SINCE:
        query = query.filter(Sighting.expire_timestamp > SINCE_TIME)
    results = query.all()
    results_dict = {r[0]: r[1] for r in results}
    filled = []
    for row_no, i in enumerate(range(int(results[0][0]), int(results[-1][0]))):
        filled.append((row_no, results_dict.get(i, 0)))
    return filled


def get_top_pokemon(session, count=30, order='DESC'):
    query = session.query(Sighting.pokemon_id, func.count(Sighting.pokemon_id).label('how_many')) \
        .group_by(Sighting.pokemon_id)
    if conf.REPORT_SINCE:
        query = query.filter(Sighting.expire_timestamp > SINCE_TIME)
    order = desc if order == 'DESC' else asc
    query = query.order_by(order('how_many')).limit(count)
    return query.all()


def get_pokemon_ranking(session):
    query = session.query(Sighting.pokemon_id, func.count(Sighting.pokemon_id).label('how_many')) \
        .group_by(Sighting.pokemon_id) \
        .order_by(asc('how_many'))
    if conf.REPORT_SINCE:
        query = query.filter(Sighting.expire_timestamp > SINCE_TIME)
    ranked = [r[0] for r in query]
    none_seen = [x for x in range(1,387) if x not in ranked]
    return none_seen + ranked

def get_gym(session,raw_fort):
    fort = session.query(Fort) \
        .filter(Fort.external_id == raw_fort['external_id']) \
        .first()
    return fort

def get_sightings_per_pokemon(session):
    query = session.query(Sighting.pokemon_id, func.count(Sighting.pokemon_id).label('how_many')) \
        .group_by(Sighting.pokemon_id) \
        .order_by('how_many')
    if conf.REPORT_SINCE:
        query = query.filter(Sighting.expire_timestamp > SINCE_TIME)
    return OrderedDict(query.all())


def sightings_to_csv(since=None, output='sightings.csv'):
    from csv import writer as csv_writer

    if since:
        conf.REPORT_SINCE = since
    with session_scope() as session:
        sightings = get_sightings_per_pokemon(session)
    od = OrderedDict()
    for pokemon_id in range(1, 387):
        if pokemon_id not in sightings:
            od[pokemon_id] = 0
    od.update(sightings)
    with open(output, 'wt') as csvfile:
        writer = csv_writer(csvfile)
        writer.writerow(('pokemon_id', 'count'))
        for item in od.items():
            writer.writerow(item)


def get_rare_pokemon(session):
    result = []

    for pokemon_id in conf.RARE_IDS:
        query = session.query(Sighting) \
            .filter(Sighting.pokemon_id == pokemon_id)
        if conf.REPORT_SINCE:
            query = query.filter(Sighting.expire_timestamp > SINCE_TIME)
        count = query.count()
        if count > 0:
            result.append((pokemon_id, count))
    return result


def get_nonexistent_pokemon(session):
    query = session.execute('''
        SELECT DISTINCT pokemon_id FROM sightings
        {report_since}
    '''.format(report_since=SINCE_QUERY))
    db_ids = [r[0] for r in query]
    return [x for x in range(1,387) if x not in db_ids]


def get_all_sightings(session, pokemon_ids):
    # TODO: rename this and get_sightings
    query = session.query(Sighting) \
        .filter(Sighting.pokemon_id.in_(pokemon_ids))
    if conf.REPORT_SINCE:
        query = query.filter(Sighting.expire_timestamp > SINCE_TIME)
    return query.all()


def get_spawns_per_hour(session, pokemon_id):
    if DB_TYPE == 'sqlite':
        ts_hour = 'STRFTIME("%H", expire_timestamp)'
    elif DB_TYPE == 'postgresql':
        ts_hour = "TO_CHAR(TO_TIMESTAMP(expire_timestamp), 'HH24')"
    else:
        ts_hour = 'HOUR(FROM_UNIXTIME(expire_timestamp))'
    query = session.execute('''
        SELECT
            {ts_hour} AS ts_hour,
            COUNT(*) AS how_many
        FROM sightings
        WHERE pokemon_id = {pokemon_id}
        {report_since}
        GROUP BY ts_hour
        ORDER BY ts_hour
    '''.format(
        pokemon_id=pokemon_id,
        ts_hour=ts_hour,
        report_since=SINCE_QUERY.replace('WHERE', 'AND')
    ))
    results = []
    for result in query:
        results.append((
            {
                'v': [int(result[0]), 30, 0],
                'f': '{}:00 - {}:00'.format(
                    int(result[0]), int(result[0]) + 1
                ),
            },
            result[1]
        ))
    return results


def get_total_spawns_count(session, pokemon_id):
    query = session.query(Sighting) \
        .filter(Sighting.pokemon_id == pokemon_id)
    if conf.REPORT_SINCE:
        query = query.filter(Sighting.expire_timestamp > SINCE_TIME)
    return query.count()


def get_all_spawn_coords(session, pokemon_id=None):
    points = session.query(Sighting.lat, Sighting.lon)
    if pokemon_id:
        points = points.filter(Sighting.pokemon_id == int(pokemon_id))
    if conf.REPORT_SINCE:
        points = points.filter(Sighting.expire_timestamp > SINCE_TIME)
    return points.all()
