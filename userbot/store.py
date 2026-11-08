import asyncio
import json
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

import aiosqlite
from cryptography.fernet import Fernet


@dataclass
class Preferences:
    keywords: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    groups: list[int] = field(default_factory=list)
    enabled: bool = False


class Store:
    def __init__(self, path: Path, key: str, owner_id: int):
        self.path = path
        self.cipher = Fernet(key.encode())
        self.owner_id = owner_id
        self.lock = asyncio.Lock()

    async def open(self):
        self.db = await aiosqlite.connect(self.path, isolation_level=None)
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA foreign_keys=ON;
            PRAGMA busy_timeout=5000;
            PRAGMA secure_delete=ON;
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, active INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, value BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS cooldowns (key TEXT PRIMARY KEY, until REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS deliveries (
                user_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                post_key TEXT NOT NULL,
                root_id INTEGER NOT NULL,
                random_id INTEGER NOT NULL,
                created REAL NOT NULL,
                state TEXT NOT NULL,
                PRIMARY KEY(user_id, group_id, post_key)
            );
            CREATE INDEX IF NOT EXISTS delivery_rate ON deliveries(user_id, created);
        """)
        row = await self.one("SELECT value FROM metadata WHERE key='key-check'")
        if row:
            if self.cipher.decrypt(row[0]) != b"discussion-userbot-v1":
                raise ValueError("SESSION_KEY does not match the database")
        else:
            await self.execute(
                "INSERT INTO metadata VALUES ('key-check', ?)",
                (self.cipher.encrypt(b"discussion-userbot-v1"),),
            )
        await self.execute("INSERT OR REPLACE INTO users VALUES (?, 1)", (self.owner_id,))

    async def close(self):
        await self.db.close()

    async def one(self, sql, values=()):
        async with self.lock, self.db.execute(sql, values) as cursor:
            return await cursor.fetchone()

    async def all(self, sql, values=()):
        async with self.lock, self.db.execute(sql, values) as cursor:
            return await cursor.fetchall()

    async def execute(self, sql, values=()):
        async with self.lock, self.db.execute(sql, values):
            pass

    async def allowed(self, user_id):
        row = await self.one("SELECT active FROM users WHERE id=?", (user_id,))
        return bool(row and row[0])

    async def grant(self, user_id, maximum):
        async with self.lock:
            async with self.db.execute("SELECT COUNT(*) FROM users WHERE active=1") as cur:
                count = (await cur.fetchone())[0]
            async with self.db.execute("SELECT active FROM users WHERE id=?", (user_id,)) as cur:
                row = await cur.fetchone()
            if row and row[0]:
                return
            if count >= maximum:
                raise ValueError("The configured account limit has been reached")
            await self.db.execute("INSERT OR REPLACE INTO users VALUES (?, 1)", (user_id,))

    async def revoke(self, user_id):
        if user_id == self.owner_id:
            raise ValueError("The owner cannot be removed")
        await self.execute("UPDATE users SET active=0 WHERE id=?", (user_id,))

    async def users(self):
        return [row[0] for row in await self.all("SELECT id FROM users WHERE active=1 ORDER BY id")]

    async def preferences(self, user_id):
        row = await self.one("SELECT value FROM preferences WHERE id=?", (user_id,))
        return Preferences(**json.loads(row[0])) if row else Preferences()

    async def save_preferences(self, user_id, preferences):
        await self.execute(
            "INSERT OR REPLACE INTO preferences VALUES (?, ?)",
            (user_id, json.dumps(asdict(preferences))),
        )

    async def save_session(self, user_id, session):
        await self.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?, ?)",
            (user_id, self.cipher.encrypt(session.encode())),
        )

    async def session(self, user_id):
        row = await self.one("SELECT value FROM sessions WHERE id=?", (user_id,))
        return self.cipher.decrypt(row[0]).decode() if row else ""

    async def delete_session(self, user_id):
        await self.execute("DELETE FROM sessions WHERE id=?", (user_id,))

    async def session_users(self):
        return [row[0] for row in await self.all("SELECT id FROM sessions WHERE id<>0")]

    async def blocked_until(self, key):
        row = await self.one("SELECT until FROM cooldowns WHERE key=?", (key,))
        return row[0] if row else 0

    async def block(self, key, until):
        await self.execute(
            "INSERT INTO cooldowns VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET until=MAX(until, excluded.until)",
            (key, until),
        )

    async def seen(self, user_id, group_id, key):
        return bool(
            await self.one(
                "SELECT 1 FROM deliveries WHERE user_id=? AND group_id=? AND post_key=?",
                (user_id, group_id, key),
            )
        )

    async def can_send(self, user_id, now, interval, hourly):
        count, latest = await self.one(
            "SELECT COUNT(*), MAX(created) FROM deliveries WHERE user_id=? AND created>?",
            (user_id, now - 3600),
        )
        return count < hourly and (latest is None or now - latest >= interval)

    async def reserve(self, user_id, group_id, key, root_id, now, interval, hourly):
        async with self.lock:
            await self.db.execute("BEGIN IMMEDIATE")
            try:
                async with self.db.execute(
                    "SELECT COUNT(*), MAX(created) FROM deliveries WHERE user_id=? AND created>?",
                    (user_id, now - 3600),
                ) as cur:
                    count, latest = await cur.fetchone()
                if count >= hourly or (latest is not None and now - latest < interval):
                    await self.db.rollback()
                    return None
                random_id = secrets.randbits(63) or 1
                async with self.db.execute(
                    "INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?, ?, ?, ?, 'reserved')",
                    (user_id, group_id, key, root_id, random_id, now),
                ) as cur:
                    inserted = cur.rowcount == 1
                await self.db.commit()
                return random_id if inserted else None
            except BaseException:
                await self.db.rollback()
                raise

    async def mark(self, user_id, group_id, key, state):
        await self.execute(
            "UPDATE deliveries SET state=? WHERE user_id=? AND group_id=? AND post_key=?",
            (state, user_id, group_id, key),
        )
