import sys
from time import time
from sqlalchemy import func
from sqlalchemy.dialects.mysql.mysqldb import MySQLDialect_mysqldb
from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2
from .db import session_scope, _engine, Sighting, Mystery, FortSighting, Raid, Spawnpoint
from .shared import get_logger
from . import sanitized as conf

log = get_logger(__name__)
    
db_dialect = None

if isinstance(_engine.dialect, MySQLDialect_mysqldb):
    db_dialect = "mysql"
elif isinstance(_engine.dialect, PGDialect_psycopg2):
    db_dialect = "pgsql"

if db_dialect is None:
    log.error("Unsupported DB dialect {}", _engine.dialect)
    sys.exit()


def del_statement(table, table_tmp):
    if db_dialect == "pgsql":
        return "DELETE FROM {} t USING {} tt WHERE t.id = tt.id".format(table, table_tmp)
    elif db_dialect == "mysql":
        return "DELETE t.* FROM {} t INNER JOIN {} tt ON t.id = tt.id".format(table, table_tmp)


def cleanup_with_temp_table(table, time, limit=conf.CLEANUP_LIMIT, time_col="updated"):
    with session_scope(autoflush=True) as session:
        log.info("Cleaning up {}...", table)

        table_tmp = "{}_tmp".format(table)
        session.execute("""
        CREATE TEMPORARY TABLE IF NOT EXISTS {}_tmp AS (
          SELECT t.id
          FROM {} t
          WHERE t.{} IS NULL OR t.{} < :time
          LIMIT :limit 
        )""".format(table, table, time_col, time_col), {
            'time': time,
            'limit': limit,
            })
        session.execute(del_statement(table, table_tmp))
        delete_count = session.execute("SELECT COUNT(*) AS delete_count FROM {}".format(table_tmp)).fetchall()
        session.execute("DROP TABLE {}".format(table_tmp))

        log.info("=> Done. {} {} deleted.", delete_count[0][0], table)


def is_service_alive():
    now = time()
    thirty_min_ago = now - (30 * 60)

    with session_scope(autoflush=True) as session:
        last_updated = session.query(func.max(FortSighting.updated)).first()[0]
        last_updated = last_updated if last_updated else 0 
        if last_updated > thirty_min_ago:
            return True 
    return False 


def light():
    now = time()
    x_hr_ago = now - (6 * 3600)

    if is_service_alive():
        if conf.CLEANUP_RAIDS_OLDER_THAN_X_HR > 0:
            cleanup_with_temp_table("raids", now - (conf.CLEANUP_RAIDS_OLDER_THAN_X_HR * 3600), time_col="time_spawn")
        if conf.CLEANUP_FORT_SIGHTINGS_OLDER_THAN_X_HR > 0:
            cleanup_with_temp_table("fort_sightings", now - (conf.CLEANUP_FORT_SIGHTINGS_OLDER_THAN_X_HR * 3600))
        if conf.CLEANUP_MYSTERY_SIGHTINGS_OLDER_THAN_X_HR > 0:
            cleanup_with_temp_table("mystery_sightings", now - (conf.CLEANUP_MYSTERY_SIGHTINGS_OLDER_THAN_X_HR * 3600), time_col="first_seen")
        if conf.CLEANUP_SIGHTINGS_OLDER_THAN_X_HR > 0:
            cleanup_with_temp_table("sightings", now - (conf.CLEANUP_SIGHTINGS_OLDER_THAN_X_HR * 3600))
    else:
        log.info("Skipping cleanup since updates seem to be stopped for more than 30 mins.")

    log.info("Light cleanup done.")


#def heavy():
#    now = time()
#
#    if is_service_alive():
#        if conf.CLEANUP_SPAWNPOINTS_OLDER_THAN_X_HR > 0:
#            cleanup_with_temp_table("spawnpoints", now - (conf.CLEANUP_SPAWNPOINTS_OLDER_THAN_X_HR * 3600))
#    else:
#        log.info("Skipping cleanup since updates seem to be stopped for more than 30 mins.")
#
#    log.info("Heavy cleanup done.")
