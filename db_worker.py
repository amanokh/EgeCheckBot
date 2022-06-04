import asyncio
import asyncpg
import config

from pypika import Table, Query, Parameter, Field
from typing import Dict, Any


class DbConnection:
    conn = None

    async def connect_db(self):
        self.conn = await asyncpg.create_pool(dsn=config.db_url)

    def __init__(self):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.connect_db())


class DbTable:
    _conn = None
    _table = None
    _pk_id = None

    def __init__(self, conn, name, columns, pk_id):
        self._conn = conn
        self._table = Table(name)
        self._pk_id = Field(pk_id)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.create_table(self._table, columns, pk_id))

    async def create_table(self, table, columns, pk_id):
        query = Query.create_table(table) \
            .if_not_exists().columns(*columns) \
            .primary_key(pk_id)
        return await self._conn.fetch(query.get_sql())

    async def get(self, key):
        query = Query.from_(self._table) \
            .select("*") \
            .where(self._pk_id == key)
        return await self._conn.fetchrow(query.get_sql())

    async def insert(self, updates: Dict[str, Any]):
        query = Query.into(self._table) \
            .columns(*updates.keys()) \
            .insert(*(Parameter("${:d}".format(i + 1)) for i in range(len(updates))))

        await self._conn.execute(query.get_sql(), *updates.values())

    async def update(self, key, updates: Dict[str, Any]):
        param_count = 0
        query = Query.update(self._table)
        for update in updates.keys():
            param_count += 1
            query = query.set(update, Parameter("${:d}".format(param_count)))
        query = query.where(self._pk_id == key)

        await self._conn.execute(query.get_sql(), *updates.values())

    async def delete(self, key):
        query = Query.from_(self._table) \
            .delete() \
            .where(self._pk_id == key)
        await self._conn.execute(query.get_sql())

    async def count(self):
        res = await self._conn.fetchrow("SELECT COUNT(*) FROM {}".format(self._table))
        return res["count"]

    async def custom_fetch(self, query, *values):
        return await self._conn.fetch(query, *values)

