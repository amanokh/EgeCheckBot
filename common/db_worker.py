import logging
import os
from typing import Dict, Any

import asyncpg
from asyncpg import Record
from pypika import Table, Query, Parameter, Field

import config

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOGLEVEL", logging.DEBUG))


async def create_db_connection():
    return await asyncpg.connect(dsn=config.db_url)


async def create_db_connection_pool(threads=10):
    return await asyncpg.create_pool(dsn=config.db_url, min_size=threads, max_size=threads)


class DbTable:
    _conn_pool: asyncpg.pool.Pool = None
    _table = None
    _columns = None
    _pk_id = None
    _if_not_exists = None
    _foreign_key_settings = None

    def __init__(self, name, columns, pk_id=None, if_not_exists=True, foreign_key_settings=None):
        self._table = Table(name)
        self._columns = columns
        self._pk_id = pk_id
        self._if_not_exists = if_not_exists
        self._foreign_key_settings = foreign_key_settings

    async def create_and_init_table(self, conn_pool):
        try:
            self._conn_pool = conn_pool
            query = Query.create_table(self._table).columns(*self._columns)
            if self._pk_id:
                query = query.primary_key(self._pk_id)

            async with self._conn_pool.acquire() as conn:
                await conn.fetch(query.get_sql())

            if self._foreign_key_settings:
                for foreign_key in self._foreign_key_settings:
                    query = "ALTER TABLE {table} ADD FOREIGN KEY ({columns}) REFERENCES {reference_table}" \
                            "({reference_columns}) {on_update} {on_delete}".format(
                        table=self._table,
                        columns=",".join(foreign_key["columns"]),
                        reference_table=foreign_key["reference_table"],
                        reference_columns=",".join(foreign_key["reference_columns"]),
                        on_delete="ON DELETE %s" % foreign_key["on_delete"].value if foreign_key["on_delete"] else "",
                        on_update="ON UPDATE %s" % foreign_key["on_update"].value if foreign_key["on_update"] else "")
                    async with self._conn_pool.acquire() as conn:
                        await conn.fetch(query)
        except asyncpg.exceptions.DuplicateTableError:
            pass

    async def get(self, key) -> Record:
        query = Query.from_(self._table) \
            .select("*") \
            .where(Field(self._pk_id) == key)
        async with self._conn_pool.acquire() as conn:
            return await conn.fetchrow(query.get_sql())

    async def insert(self, updates: Dict[str, Any]):
        query = Query.into(self._table) \
            .columns(*updates.keys()) \
            .insert(*(Parameter("${:d}".format(i + 1)) for i in range(len(updates))))
        async with self._conn_pool.acquire() as conn:
            await conn.execute(query.get_sql(), *updates.values())

    async def update(self, key, updates: Dict[str, Any]):
        param_count = 0
        query = Query.update(self._table)
        for update in updates.keys():
            param_count += 1
            query = query.set(update, Parameter("${:d}".format(param_count)))
        query = query.where(Field(self._pk_id) == key)
        async with self._conn_pool.acquire() as conn:
            await conn.execute(query.get_sql(), *updates.values())

    async def delete(self, key):
        query = Query.from_(self._table) \
            .delete() \
            .where(Field(self._pk_id) == key)
        async with self._conn_pool.acquire() as conn:
            await conn.execute(query.get_sql())

    async def count(self):
        async with self._conn_pool.acquire() as conn:
            res = await conn.fetchrow("SELECT COUNT(*) FROM {}".format(self._table))
            return res["count"]

    async def custom_fetch(self, query, *params):
        async with self._conn_pool.acquire() as conn:
            return await conn.fetch(query, *params)
