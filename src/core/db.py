# ==========================
# LRE-BOT/src/core/db.py
# ==========================
import aiosqlite
import time
import os
import sqlite3
from pathlib import Path
from core import config

# ─── CONFIGURATION DB ─────────────────────────────────────
DB_PATH = config.DB_PATH

# Création du dossier de la DB si nécessaire
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# Résolution sûre du chemin vers init_db.sql
BASE_DIR = Path(__file__).resolve().parents[2]  # remonte jusqu’à LRE-BOT-main/
SCHEMA_PATH = BASE_DIR / "init_db.sql"


# ─── UTILS ────────────────────────────────────────────────

def now_ts() -> int:
    """Timestamp actuel en secondes UTC"""
    return int(time.time())


# ─── INIT DB ──────────────────────────────────────────────

async def init_db():
    """Crée les tables si elles n'existent pas déjà."""
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"❌ init_db.sql introuvable à : {SCHEMA_PATH}")

    async with aiosqlite.connect(DB_PATH) as db:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            sql_script = f.read()
        await db.executescript(sql_script)
        await db.commit()
        print(f"[DB] Initialisation OK → {DB_PATH}")


# ─── SETTINGS ─────────────────────────────────────────────

async def get_setting(key: str, default=None, cast=str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        if row and row[0] is not None:
            try:
                return cast(row[0])
            except (ValueError, TypeError):
                return default
        return default


async def set_setting(key: str, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, str(value)),
        )
        await db.commit()


async def get_maintenance(guild_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT value FROM settings WHERE key=?",
            (f"maintenance_{guild_id}",),
        )
        row = await cur.fetchone()
        return row and row[0] == "1"


async def set_maintenance(guild_id: int, enabled: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (f"maintenance_{guild_id}", "1" if enabled else "0"),
        )
        await db.commit()


def get_prefix():
    import asyncio
    return asyncio.run(get_setting("prefix", "*"))


# ─── USERS ────────────────────────────────────────────────

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


async def get_user(user_id: int, guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT user_id, username, join_date, leave_date,
                   total_time, total_A, total_B, pause_A, pause_B,
                   sessions_count, streak_current, streak_best
            FROM users WHERE user_id=?
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None

        keys = [
            "user_id", "username", "join_date", "leave_date",
            "total_time", "total_A", "total_B", "pause_A", "pause_B",
            "sessions_count", "streak_current", "streak_best"
        ]
        return dict(zip(keys, row))


# ─── PARTICIPANTS ─────────────────────────────────────────

async def add_participant(guild_id: int, user_id: int, mode: str) -> bool:
    """
    Ajoute l'utilisateur comme participant si pas déjà présent.
    Retourne True si nouvel ajout, False si déjà inscrit.
    Opération atomique pour éviter les courses concurrentes.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Verrouiller la DB pour éviter race conditions entre deux appels concurrents
        await db.execute("BEGIN IMMEDIATE")
        cur = await db.execute(
            "SELECT 1 FROM participants WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        exists = await cur.fetchone()
        if exists:
            await db.commit()
            return False

        ts = now_ts()
        await db.execute(
            """
            INSERT INTO participants (guild_id, user_id, join_ts, mode, validated)
            VALUES (?, ?, ?, ?, 0)
            """,
            (guild_id, user_id, ts, mode),
        )
        await db.commit()
        return True


async def remove_participant(guild_id: int, user_id: int):
    """
    Retire l'utilisateur et retourne (join_ts, mode) si existait, sinon (None, None).
    Opération atomique pour éviter double-suppression/races.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")
        cur = await db.execute(
            "SELECT join_ts, mode FROM participants WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        if not row:
            await db.commit()
            return (None, None)

        await db.execute(
            "DELETE FROM participants WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        await db.commit()
        return row


async def get_participants(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, join_ts, mode, validated FROM participants WHERE guild_id=?",
            (guild_id,),
        )
        return await cur.fetchall()


# ─── TEMPS / STATS ────────────────────────────────────────

async def ajouter_temps(user_id: int, guild_id: int, elapsed: int, mode: str, is_session_end=False):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, join_date) VALUES (?, ?, ?)",
            (user_id, "", now_ts()),
        )

        if mode == "A":
            await db.execute(
                """
                UPDATE users
                SET total_time = total_time + ?,
                    total_A = total_A + ?,
                    sessions_count = sessions_count + ?
                WHERE user_id=?
                """,
                (elapsed, elapsed, 1 if is_session_end else 0, user_id),
            )
        elif mode == "B":
            await db.execute(
                """
                UPDATE users
                SET total_time = total_time + ?,
                    total_B = total_B + ?,
                    sessions_count = sessions_count + ?
                WHERE user_id=?
                """,
                (elapsed, elapsed, 1 if is_session_end else 0, user_id),
            )
        await db.commit()


async def clear_all_stats(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users")
        await db.execute("DELETE FROM participants WHERE guild_id=?", (guild_id,))

        # stickies : essayer suppression par guild_id puis fallback sur ancienne structure
        try:
            await db.execute("DELETE FROM stickies WHERE guild_id=?", (guild_id,))
        except (sqlite3.OperationalError, Exception):
            try:
                await db.execute("DELETE FROM stickies")
            except Exception:
                pass

        await db.commit()


async def get_server_stats(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*), SUM(total_time), AVG(total_time) FROM users"
        )
        row = await cur.fetchone()
        return {
            "users": row[0] or 0,
            "total_time": row[1] or 0,
            "avg_time": int(row[2] or 0),
        }


async def get_leaderboards(guild_id: int):
    results = {
        "🌍 Top 10 - Global": [],
        "🥇 Top 5 - Mode A": [],
        "🥈 Top 5 - Mode B": [],
        "🔄 Top 5 - Sessions": [],
        "🔥 Top 5 - Streaks": [],
    }

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, total_time FROM users ORDER BY total_time DESC LIMIT 10"
        )
        results["🌍 Top 10 - Global"] = await cur.fetchall()

        cur = await db.execute(
            "SELECT user_id, total_A FROM users ORDER BY total_A DESC LIMIT 5"
        )
        results["🥇 Top 5 - Mode A"] = await cur.fetchall()

        cur = await db.execute(
            "SELECT user_id, total_B FROM users ORDER BY total_B DESC LIMIT 5"
        )
        results["🥈 Top 5 - Mode B"] = await cur.fetchall()

        cur = await db.execute(
            "SELECT user_id, sessions_count FROM users ORDER BY sessions_count DESC LIMIT 5"
        )
        results["🔄 Top 5 - Sessions"] = await cur.fetchall()

        cur = await db.execute(
            "SELECT user_id, streak_current, streak_best FROM users ORDER BY streak_best DESC LIMIT 5"
        )
        results["🔥 Top 5 - Streaks"] = await cur.fetchall()

    return results


# ─── STICKIES ─────────────────────────────────────────────

async def set_sticky(guild_id: int, channel_id: int, message_id: int, content: str, author_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT OR REPLACE INTO stickies (guild_id, channel_id, message_id, content, author_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, channel_id, message_id, content, author_id),
            )
        except (sqlite3.OperationalError, Exception):
            try:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO stickies (channel_id, message_id, text, requested_by)
                    VALUES (?, ?, ?, ?)
                    """,
                    (channel_id, message_id, content, author_id),
                )
            except Exception:
                pass
        await db.commit()


async def get_sticky(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cur = await db.execute(
                "SELECT message_id, content, author_id FROM stickies WHERE guild_id=? AND channel_id=?",
                (guild_id, channel_id),
            )
            row = await cur.fetchone()
            return row
        except (sqlite3.OperationalError, Exception):
            try:
                cur = await db.execute(
                    "SELECT message_id, text, requested_by FROM stickies WHERE channel_id=?",
                    (channel_id,),
                )
                return await cur.fetchone()
            except Exception:
                return None


async def remove_sticky(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "DELETE FROM stickies WHERE guild_id=? AND channel_id=?",
                (guild_id, channel_id),
            )
        except (sqlite3.OperationalError, Exception):
            try:
                await db.execute("DELETE FROM stickies WHERE channel_id=?", (channel_id,))
            except Exception:
                pass
        await db.commit()
