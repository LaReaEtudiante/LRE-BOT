# ==========================
# LRE-BOT/src/core/db.py
# ==========================
import aiosqlite
from core import config

DB_PATH = config.DB_PATH


async def init_db():
    """Crée les tables si elles n'existent pas déjà"""
    async with aiosqlite.connect(DB_PATH) as db:
        with open("init_db.sql", "r", encoding="utf-8") as f:
            await db.executescript(f.read())
        await db.commit()


# ─── SETTINGS ─────────────────────────────────────────────────────

async def get_setting(key: str, default=None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()


# ─── USERS ────────────────────────────────────────────────────────

async def upsert_user(user_id: int, username: str, join_date: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (user_id, username, join_date)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username
            """,
            (user_id, username, join_date),
        )
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        return await cur.fetchone()


# ─── PARTICIPANTS (sessions actives) ─────────────────────────────

async def add_participant(guild_id: int, user_id: int, join_ts: int, mode: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO participants (guild_id, user_id, join_ts, mode, validated)
            VALUES (?, ?, ?, ?, 0)
            """,
            (guild_id, user_id, join_ts, mode),
        )
        await db.commit()


async def remove_participant(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM participants WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        await db.commit()


async def get_participants(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, join_ts, mode, validated FROM participants WHERE guild_id=?",
            (guild_id,),
        )
        return await cur.fetchall()


# ─── STICKIES ────────────────────────────────────────────────────

async def set_sticky(guild_id: int, channel_id: int, message_id: int, content: str, author_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO stickies (guild_id, channel_id, message_id, content, author_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild_id, channel_id, message_id, content, author_id),
        )
        await db.commit()


async def get_sticky(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT message_id, content, author_id FROM stickies WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        return await cur.fetchone()


async def remove_sticky(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM stickies WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        await db.commit()
