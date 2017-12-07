import os
import enum
import csv
from asyncio import run_coroutine_threadsafe
from time import time, monotonic
from queue import Queue
from threading import Semaphore
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, UniqueConstraint, Index, exists, func, or_
from sqlalchemy.types import Integer, Boolean, Enum, SmallInteger, String
from . import db, utils, sanitized as conf
from .shared import LOOP, get_logger, run_threaded
            
log = get_logger(__name__)

instance_id = conf.INSTANCE_ID[-32:]
bucket = {}
account_get_sem = Semaphore()

RESERVE_TYPE_SLAVE = 0
RESERVE_TYPE_CAPTAIN = 1

class Provider(enum.Enum):
    ptc = 1
    google = 2 


class MonocleDialect(csv.Dialect):
    delimiter=','
    quotechar='"'
    quoting=csv.QUOTE_MINIMAL
    lineterminator='\n'
    skipinitialspace=True


class GomanDialect(csv.Dialect):
    delimiter=':'
    quotechar='"'
    quoting=csv.QUOTE_MINIMAL
    lineterminator='\n'
    skipinitialspace=True


class Account(db.Base):
    __tablename__ = 'accounts'

    id = Column(Integer, primary_key=True)
    instance = Column(String(32), index=True, nullable=True)
    username = Column(String(32), nullable=False)
    password = Column(String(32), nullable=False)
    provider = Column(String(12), nullable=False)
    level = Column(SmallInteger, default=1, nullable=False, index=True)
    reserve_type = Column(SmallInteger, default=0, nullable=True)
    model = Column(String(20))
    device_version = Column(String(20))
    device_id = Column(String(64))
    remove = Column(Boolean, default=False)
    hibernated = Column(Integer, index=True)
    last_hibernated = Column(Integer, index=True)
    reason = Column(String(12), index=True)
    captchaed = Column(Integer, index=True)
    created = Column(Integer, default=time)
    binded = Column(Integer, default=time, index=True)
    updated = Column(Integer, default=time, onupdate=time)
    
    __table_args__ = (
        UniqueConstraint(
            'username',
            name='ix_accounts_username_unique'
        ),
        Index('ix_accounts_acquisition', "reserve_type", "instance", "hibernated", "created"),
    )

    stats_info = (0, None, None)

    @staticmethod
    def to_account_dict(account):
        d = {
                'instance': account.instance,
                'internal_id': account.id,
                'username': account.username,
                'password': account.password,
                'provider': account.provider,
                'level': account.level,
                'model': account.model,
                'iOS': account.device_version,
                'id': account.device_id,
                }
        if account.remove:
            d['remove'] = True
        if account.captchaed and not conf.CAPTCHA_KEY:
            d['captcha'] = True
        if account.hibernated:
            if account.reason == 'sbanned':
                d['sbanned'] = True
            elif account.reason == 'warn':
                d['warn'] = True
            elif account.reason == 'banned':
                d['banned'] = True
            elif account.reason == 'code3':
                d['code3'] = True
            elif account.reason == 'credentials':
                d['credentials'] = True
            elif account.reason == 'unverified':
                d['unverified'] = True
            elif account.reason == 'security':
                d['security'] = True
            elif account.reason == 'temp_disabled':
                d['temp_disabled'] = True
        return d

    @staticmethod
    def copy_dict_data(from_dict, to_dict):
        to_dict['password'] = from_dict['password']
        to_dict['model'] = from_dict['model']
        to_dict['iOS'] = from_dict['iOS']
        to_dict['id'] = from_dict['id']
        if 'remove' in from_dict:
            to_dict['remove'] = from_dict['remove']
        if 'level' in from_dict and from_dict['level']:
            to_dict['level'] = from_dict.get('level')
        if 'internal_id' in from_dict:
            to_dict['internal_id'] = from_dict['internal_id']
        if 'captcha' in from_dict:
            to_dict['captcha'] = from_dict.get('captcha')
        elif 'captcha' in to_dict:
            del to_dict['captcha']
        if 'banned' in from_dict:
            to_dict['banned'] = from_dict.get('banned')
        elif 'banned' in to_dict:
            del to_dict['banned']
        if 'sbanned' in from_dict:
            to_dict['sbanned'] = from_dict.get('sbanned')
        elif 'sbanned' in to_dict:
            del to_dict['sbanned']
        if 'code3' in from_dict:
            to_dict['code3'] = from_dict.get('code3')
        elif 'code3' in to_dict:
            del to_dict['code3']
        if 'credentials' in from_dict:
            to_dict['credentials'] = from_dict.get('credentials')
        elif 'credentials' in to_dict:
            del to_dict['credentials']
        if 'unverified' in from_dict:
            to_dict['unverified'] = from_dict.get('unverified')
        elif 'unverified' in to_dict:
            del to_dict['unverified']
        if 'security' in from_dict:
            to_dict['security'] = from_dict.get('security')
        elif 'security' in to_dict:
            del to_dict['security']
        if 'temp_disabled' in from_dict:
            to_dict['temp_disabled'] = from_dict.get('temp_disabled')
        elif 'temp_disabled' in to_dict:
            del to_dict['temp_disabled']

    @staticmethod
    def from_account_dict(session, account_dict, account_db=None, assign_instance=True, update_flags=True):
        account = {}

        for k in account_dict:
            v = account_dict[k]
            if v is not None:
                account[k] = v

        username = account['username']
        if not account_db and 'internal_id' in account:
            account_db = session.query(Account) \
                    .filter(Account.id==account['internal_id']) \
                    .with_lockmode("update") \
                    .first()
        if not account_db:
            account_db = Account.lookup(session, username, lock=True)
        if not account_db:
            account_db = Account(username=username)

        if assign_instance:
            account_db.instance = instance_id
        if 'provider' in account:
            account_db.provider = account.get('provider')
        else:
            account_db.provider = 'ptc'

        if 'password' in account:
            account_db.password = account.get('password')
        if 'level' in account:
            account_db.level = account.get('level', 0)
            account_db.reserve_type = RESERVE_TYPE_SLAVE if account_db.level < 30 else RESERVE_TYPE_CAPTAIN
        if 'model' in account:
            account_db.model = account.get('model')
        if 'iOS' in account:
            account_db.device_version = account.get('iOS')
        if 'id' in account:
            account_db.device_id = account.get('id')
        if 'graduated' in account and account['graduated']:
            account_db.instance = None
        if 'demoted' in account and account['demoted']:
            account_db.instance = None
        if 'remove' in account:
            account_db.remove = account.get('remove', False)

        if update_flags:
            if 'captcha' in account:
                account_db.captchaed = int(time())
            else:
                account_db.captchaed = None

            if 'banned' in account and account['banned']:
                account_db.reason = 'banned'
            elif 'sbanned' in account and account['sbanned']:
                account_db.reason = 'sbanned'
            elif 'warn' in account and account['warn']:
                account_db.reason = 'warn'
            elif 'code3' in account and account['code3']:
                account_db.reason = 'code3'
            elif 'credentials' in account and account['credentials']:
                account_db.reason = 'credentials'
            elif 'unverified' in account and account['unverified']:
                account_db.reason = 'unverified'
            elif 'security' in account and account['security']:
                account_db.reason = 'security'
            elif 'temp_disabled' in account and account['temp_disabled']:
                account_db.reason = 'temp_disabled'
            else:
                account_db.hibernated = None
                account_db.reason = None

            if account_db.reason:
                account_db.hibernated = int(time())
                account_db.last_hibernated = account_db.hibernated
        return account_db

    @staticmethod
    def load_my_accounts(instance_id, usernames):
        with db.session_scope() as session:
            q = session.query(Account) \
                .filter(Account.hibernated==None)
            if len(usernames) > 0:
                q = q.filter(or_(
                    Account.username.in_(usernames),
                    Account.instance==instance_id))
            else:
                q = q.filter(Account.instance==instance_id)
            accounts = q.all()
            clean_accounts = [Account.to_account_dict(account) for account in accounts if not account.remove]
            # Delete remove flag accounts
            for account in accounts:
                if account.remove:
                    session.delete(account)
            return clean_accounts

    @staticmethod
    def query_builder(session, min_level, max_level):
        q = session.query(Account) \
                .filter(Account.instance==None,
                        Account.hibernated==None) \
                .order_by(Account.created, Account.id)
        if min_level:
            q = q.filter(Account.level >= min_level)
        if max_level:
            q = q.filter(Account.level <= max_level)
        if max_level < 30:
            q = q.filter(Account.reserve_type == RESERVE_TYPE_SLAVE)
        elif min_level >= 30:
            q = q.filter(Account.reserve_type == RESERVE_TYPE_CAPTAIN)
        return q

    @staticmethod
    def get(min_level, max_level):
        with account_get_sem:
            with db.session_scope() as session:
                q = Account.query_builder(session, min_level, max_level)
                account = q.with_lockmode("update").first()
                if account:
                    account.instance = instance_id
                    account.binded = time()
                    account_dict = Account.to_account_dict(account)
                    log.info("New account {}(Lv.{}) acquired and binded to this instance in DB.", account.username, account.level)
                else:
                    account_dict = None
        return account_dict


    @staticmethod
    def put(account_dict):
        with account_get_sem:
            if 'remove' in account_dict and account_dict['remove']: 
                return
            with db.session_scope() as session:
                account = Account.from_account_dict(session, account_dict, assign_instance=True)
                if account.remove:
                    if account.id:
                        session.delete(account)
                    account_dict['remove'] = True
                else:
                    session.merge(account)
                    session.commit()
                    account_dict['internal_id'] = account.id


    @staticmethod
    def swapin():
        with db.session_scope() as session:
            swapin_count = 0
            model = session.query(Account) \
                .filter(Account.hibernated <= int(time() - conf.ACCOUNTS_HIBERNATE_DAYS * 24 * 3600))
            swapin_count += model.filter(Account.reason == 'warn') \
                .update({'hibernated': None, 'instance': None})
            swapin_count += model.filter(Account.reason == 'banned') \
                .update({'hibernated': None, 'instance': None})
            swapin_count += model.filter(Account.reason == 'sbanned') \
                .update({'hibernated': None, 'instance': None})
            swapin_count += model.filter(Account.reason == 'code3') \
                .update({'hibernated': None, 'instance': None})
            swapin_count += model.filter(Account.reason == 'temp_disabled') \
                .update({'hibernated': None, 'instance': None})
        log.info("=> Done hibernated swap in. {} accounts swapped in.", swapin_count)

    @staticmethod
    def lookup(session, username, lock=False):
        account_db = session.query(Account) \
                .filter(Account.username==username)
        if lock:
            account_db.with_lockmode("update")
        return account_db.first()

    @staticmethod
    def stats():
        if Account.stats_info:
            if Account.stats_info[0] > int(time() - 1 * 60):
                return Account.stats_info

        with db.session_scope() as session:
            accounts = session.query(Account.reason,func.count(Account.id)) \
                    .filter(Account.instance==instance_id) \
                    .group_by(Account.reason) \
                    .all()
            instance = {}
            for k, v in accounts:
                if k:
                    instance[k] = v
                else:
                    instance['good'] = v

            db_wide = {}
            common = db.get_common(session, 'account_stats_updated')
            if not common.val or int(common.val) < int(time() - 1 * 60):
                common.val = str(int(time()))
                session.merge(common)
                session.commit()

                accounts = session.query(Account) \
                        .filter(Account.instance == None,
                                Account.reserve_type == RESERVE_TYPE_SLAVE,
                                Account.reason == None) \
                        .count()
                db_wide['clean'] = accounts
                common = db.get_common(session, 'account_stats_clean',lock=True)
                common.val = str(db_wide['clean'])
                session.merge(common)

                accounts = session.query(Account) \
                        .filter(Account.instance == None,
                                Account.reserve_type == RESERVE_TYPE_SLAVE,
                                Account.hibernated == None,
                                Account.reason != None) \
                        .count()
                db_wide['test'] = accounts 
                common = db.get_common(session, 'account_stats_test',lock=True)
                common.val = str(db_wide['test'])
                session.merge(common)

                accounts = session.query(Account) \
                        .filter(Account.instance == None,
                                Account.reserve_type == RESERVE_TYPE_CAPTAIN,
                                Account.reason == None) \
                        .count()
                db_wide['clean30'] = accounts 
                common = db.get_common(session, 'account_stats_clean30',lock=True)
                common.val = str(db_wide['clean30'])
                session.merge(common)

                accounts = session.query(Account) \
                        .filter(Account.instance == None,
                                Account.reserve_type == RESERVE_TYPE_CAPTAIN,
                                Account.hibernated == None,
                                Account.reason != None) \
                        .count()
                db_wide['test30'] = accounts 
                common = db.get_common(session, 'account_stats_test30',lock=True)
                common.val = str(db_wide['test30'])
                session.merge(common)
            else:
                common = db.get_common(session, 'account_stats_clean')
                db_wide['clean'] = int(common.val or 0)
                common = db.get_common(session, 'account_stats_test')
                db_wide['test'] = int(common.val or 0)
                common = db.get_common(session, 'account_stats_clean30')
                db_wide['clean30'] = int(common.val or 0)
                common = db.get_common(session, 'account_stats_test30')
                db_wide['test30'] = int(common.val or 0)

            Account.stats_info = (time(), instance, db_wide)

        return Account.stats_info

    @classmethod
    def estimated_extra_accounts(cls, level30=False):
        dbwide = cls.stats_info[2]
        if dbwide:
            if not level30:
                return dbwide.get('clean', 0) + dbwide.get('test', 0)
            else:
                return dbwide.get('clean30', 0) + dbwide('test30', 0)
        else:
            return 0

    @staticmethod
    def import_file(file_location, level=0, assign_instance=True):
        """
        Specify force_level to update level.
        Otherwise, it will be set to 0 when level info is not available in pickles. 
        Level will be automatically updated upon login.
        """
        clean_accounts, pickled_accounts, clean_accounts30 = load_accounts_tuple()

        imported = {}

        with open(file_location, 'rt') as f:
            csv_reader = csv.reader(f)
            csv_headings = next(csv_reader)
            fieldnames = ['username','password','provider','model','iOS','id']
            if csv_headings == fieldnames:
                print("=> Input file recognized as Monocle accounts.csv format")
                fieldnames = None
                dialect = MonocleDialect
            elif "".join(csv_headings).startswith("# Batch creation start at"):
                print("=> Input file recognized as Kinan format")
                dialect = "kinan"
            else:
                print("=> Input file recognized as Goman format")
                dialect = GomanDialect
            total = 0
            for line in f:
                total += 1
            if total == 0:
                total = 1

        with open(file_location, 'rt') as f:
            if dialect == "kinan":
                reader = f
            else:
                reader = csv.DictReader(f, fieldnames=fieldnames, dialect=dialect)
            with db.session_scope() as session:
                new_count = 0
                update_count = 0
                pickle_count = 0
                idx = 0
                for line in reader:
                    idx += 1
                    if dialect == "kinan":
                        if line.startswith("#") or not line.strip():
                            continue
                        else:
                            parts = line.split(";")
                            if parts[5] == "OK":
                                row = {'username': parts[0], 'password': parts[1], 'provider': 'ptc'}
                            else:
                                continue
                    else:
                        row = line
                    username = row['username']
                    password = row['password'].strip().strip(',')

                    if username in imported:
                        continue

                    account_db = Account.lookup(session, username, lock=True)

                    if not account_db:
                        account_db = Account(username=username)
                        new_count += 1
                    else:
                        update_count += 1

                    if username in clean_accounts:
                        clean_account = clean_accounts[username]
                        account = {k:clean_account[k] for k in row}
                        account['password'] = password   # Allow password change
                        if pickled_accounts and username in pickled_accounts:
                            pickle_count += 1
                    elif account_db.id:
                        account = row
                    else:
                        account = utils.generate_device_info(row)
                        account['level'] = level

                    account_db = Account.from_account_dict(session,
                            account,
                            account_db=account_db,
                            assign_instance=assign_instance,
                            update_flags=False)
                    if account_db.remove:
                        if account_db.id:
                            session.delete(account_db)
                    else:
                        session.merge(account_db)

                    imported[username] = True

                    if idx % 10 == 0:
                        print("=> ({}/100)% imported.".format(int(100 * idx / total)))
                    if idx % 1000 == 0:
                        session.commit()

                print("=> {} new accounts inserted.".format(new_count))
                print("=> {} existing accounts in DB updated as ncessary.".format(update_count))
                print("=> {} accounts updated with data found in pickle.".format(pickle_count))

class InsufficientAccountsException(Exception):
    pass

class LoginCredentialsException(Exception):
    pass

class EmailUnverifiedException(Exception):
    pass

class SecurityLockException(Exception):
    pass

class TempDisabledException(Exception):
    pass

class CustomQueue(Queue):
    def full_wait(self, maxsize=0, timeout=None):
        '''Block until queue size falls below maxsize'''
        starttime = monotonic()
        with self.not_full:
            if maxsize > 0:
                if timeout is None:
                    while self._qsize() >= maxsize:
                        self.not_full.wait()
                elif timeout < 0:
                    raise ValueError("'timeout' must be a non-negative number")
                else:
                    endtime = monotonic() + timeout
                    while self._qsize() >= maxsize:
                        remaining = endtime - monotonic()
                        if remaining <= 0.0:
                            raise Full
                        self.not_full.wait(remaining)
            self.not_empty.notify()
        endtime = monotonic()
        return endtime - starttime

class AccountQueue(Queue):
    def min_max_level(self):
        return (0,29)

    def _put(self, item):
        Account.put(item)
        if 'remove' in item and item['remove']:
            pass
        else:
            super()._put(item)

    def get(self, block=True, timeout=None):
        if self.qsize() == 0:
            min_lv, max_lv = self.min_max_level()
            new_account = Account.get(min_lv, max_lv)
            if new_account:
                self.queue.append(new_account)
            else:
                raise InsufficientAccountsException("Not enough accounts in DB in {}".format(self.__class__.__name__)) 
        return super().get(block=block, timeout=timeout)

class Lv30AccountQueue(AccountQueue):
    def min_max_level(self):
        return (30,100)

class CaptchaAccountQueue(CustomQueue):
    def _init(self, maxsize):
        super()._init(maxsize)

    def _qsize(self):
        return super()._qsize()

    def _put(self, item):
        Account.put(item)
        if 'remove' in item and item['remove']:
            pass
        else:
            super()._put(item)

    def _get(self):
        return super()._get()


def add_account_to_keep(dirty_accounts, add_account, clean_accounts):
    if 'remove' in add_account and add_account['remove']:
        return
    username = add_account['username']
    if username in dirty_accounts and dirty_accounts[username]:
        account = dirty_accounts[username]
        if add_account['instance'] == instance_id:
            Account.copy_dict_data(add_account, account)
            clean_accounts[username] = account
        elif account:
            log.info("Removed account {} Lv.{} from this instance",
                username, add_account.get('level', 0))
    else:
        clean_accounts[username] = add_account 
        log.info("New account {} Lv.{} downloaded from DB.",
                username, add_account.get('level', 0))

def load_accounts_tuple():
    pickled_accounts = utils.load_pickle('accounts')
    accounts30 = utils.load_pickle('accounts30')

    if not accounts30:
        accounts30 = {}

    if conf.ACCOUNTS_CSV:
        accounts = load_accounts_csv()
        if pickled_accounts and set(pickled_accounts) == set(accounts):
            accounts = pickled_accounts
        else:
            accounts = accounts_from_csv(accounts, pickled_accounts)
            if pickled_accounts:
                for k in pickled_accounts:
                    if k not in accounts:
                        accounts[k] = pickled_accounts[k]
    elif conf.ACCOUNTS:
        if pickled_accounts and set(pickled_accounts) == set(acc[0] for acc in conf.ACCOUNTS):
            accounts = pickled_accounts
        else:
            accounts = accounts_from_config(pickled_accounts)
            if pickled_accounts:
                for k in pickled_accounts:
                    if k not in accounts:
                        accounts[k] = pickled_accounts[k]
    else:
        accounts = pickled_accounts 
        if not accounts:
            accounts = {} 

    # Sync db and pickle
    accounts_dicts = Account.load_my_accounts(instance_id, accounts.keys())
    clean_accounts = {}
    clean_accounts30 = {}
    for account_dict in accounts_dicts:
        level = account_dict['level']
        if not level or level < 30:
            add_account_to_keep(accounts, account_dict, clean_accounts)
        else:
            add_account_to_keep(accounts30, account_dict, clean_accounts30)

    # Save once those accounts found in pickles and configs
    for username in accounts:
        account_dict = accounts[username]
        if 'internal_id' not in account_dict:
            if 'captcha' in account_dict:
                del account_dict['captcha']
            clean_accounts[username] = account_dict
            log.info("Saving account {} Lv.{} found in pickle/config to DB",
                username, account_dict.get('level', 0))

    utils.dump_pickle('accounts', clean_accounts)
    utils.dump_pickle('accounts30', clean_accounts30)
    return clean_accounts, pickled_accounts, clean_accounts30

def create_account_dict(account):
    if isinstance(account, (tuple, list)):
        length = len(account)
    else:
        raise TypeError('Account must be a tuple or list.')

    if length not in (1, 3, 4, 6):
        raise ValueError('Each account should have either 3 (account info only) or 6 values (account and device info).')
    if length in (1, 4) and (not conf.PASS or not conf.PROVIDER):
        raise ValueError('No default PASS or PROVIDER are set.')

    entry = {}
    entry['username'] = account[0]

    if length == 1 or length == 4:
        entry['password'], entry['provider'] = conf.PASS, conf.PROVIDER
    else:
        entry['password'], entry['provider'] = account[1:3]

    if length == 4 or length == 6:
        entry['model'], entry['iOS'], entry['id'] = account[-3:]
    else:
        entry = utils.generate_device_info(entry)

    entry['time'] = 0
    entry['captcha'] = False
    entry['banned'] = False

    return entry


def load_accounts_csv():
    csv_location = os.path.join(conf.DIRECTORY, conf.ACCOUNTS_CSV)
    with open(csv_location, 'rt') as f:
        accounts = {}
        reader = csv.DictReader(f)
        for row in reader:
            accounts[row['username']] = dict(row)
    return accounts


def accounts_from_config(pickled_accounts=None):
    accounts = {}
    for account in conf.ACCOUNTS:
        username = account[0]
        if pickled_accounts and username in pickled_accounts:
            accounts[username] = pickled_accounts[username]
            if len(account) == 3 or len(account) == 6:
                accounts[username]['password'] = account[1]
                accounts[username]['provider'] = account[2]
        else:
            accounts[username] = create_account_dict(account)
    return accounts


def accounts_from_csv(new_accounts, pickled_accounts):
    accounts = {}
    for username, account in new_accounts.items():
        if pickled_accounts:
            pickled_account = pickled_accounts.get(username)
            if pickled_account:
                if pickled_account['password'] != account['password']:
                    del pickled_account['password']
                account.update(pickled_account)
            accounts[username] = account
            continue
        account['provider'] = account.get('provider') or 'ptc'
        if not all(account.get(x) for x in ('model', 'iOS', 'id')):
            account = utils.generate_device_info(account)
        account['time'] = 0
        account['captcha'] = False
        account['banned'] = False
        accounts[username] = account
    return accounts

def get_accounts():
    if 'ACCOUNTS' not in bucket:
        bucket['ACCOUNTS'], _, bucket['ACCOUNTS30'] = load_accounts_tuple() 
    return bucket['ACCOUNTS'] 

def get_accounts30():
    if 'ACCOUNTS30' not in bucket:
        bucket['ACCOUNTS'], _, bucket['ACCOUNTS30'] = load_accounts_tuple() 
    return bucket['ACCOUNTS30'] 
