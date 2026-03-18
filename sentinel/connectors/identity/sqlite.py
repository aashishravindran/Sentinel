import aiosqlite

from sentinel.core.base import IdentityConnector


class SQLiteIdentityConnector(IdentityConnector):
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def get_tags(self, user_id: str) -> set[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT tag FROM permissions WHERE user_id = ?", (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return {row[0] for row in rows}
