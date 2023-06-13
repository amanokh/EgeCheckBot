import logging
import os

from pypika import Column

import config
from common import db_worker
from common.db_worker import DbTable

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOGLEVEL", logging.DEBUG))

conn_pool = None

users_table = DbTable(config.db_table_users,
                      (Column("chat_id", "bigint", nullable=False),
                       Column("region", "int", nullable=False),
                       Column("notify", "int", nullable=False, default=1),
                       Column("token", "text", nullable=False),
                       Column("login_date", "int"),
                       Column("exams", "int[]", default="{}"),
                       Column("exams_hash", "text")),
                      pk_id="chat_id")
login_table = DbTable(config.db_table_login,
                      (Column("chat_id", "bigint", nullable=False),
                       Column("status", "text", nullable=False),
                       Column("_name", "text"),
                       Column("region", "int"),
                       Column("passport", "text"),
                       Column("captcha_token", "text"),
                       Column("captcha_answer", "text")),
                      pk_id="chat_id")

regions_table = DbTable(config.db_table_regions,
                        (Column("region", "int", nullable=False),
                         Column("exams", "int[]", default="{}"),
                         Column("notified_exams", "int[]", default="{}")),
                        pk_id="region")

examsinfo_table = DbTable(config.db_table_examsinfo,
                          (Column("exam_id", "int", nullable=False),
                           Column("title", "text", nullable=False),
                           Column("exam_date", "date"),
                           Column("res_date_official", "date"),
                           Column("res_date_predicted", "date")),
                          pk_id="exam_id")

stats_table = DbTable(config.db_table_stats,
                      (Column("user_hash", "text", nullable=False),
                       Column("first_login_time", "int", nullable=False),
                       Column("exams", "int[]"),
                       Column("region", "int")),
                      pk_id="user_hash")


async def init_db():
    global conn_pool
    global users_table
    global login_table
    global regions_table
    global examsinfo_table
    global stats_table

    conn_pool = await db_worker.create_db_connection_pool()

    await users_table.create_and_init_table(conn_pool)
    await login_table.create_and_init_table(conn_pool)
    await regions_table.create_and_init_table(conn_pool)
    await examsinfo_table.create_and_init_table(conn_pool)
    await stats_table.create_and_init_table(conn_pool)

    logger.info("Databases were initialized successfully.")
