# ==========================
# LRE-BOT/src/core/db.py
# ==========================
import aiosqlite
import sqlite3
import time
import os
from pathlib import Path
from core import config

DB_PATH = getattr(config, "DB_PATH", "data/lre.db")

# Assurer le dossier
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# utilitaires
def now_ts() -> int:
    return int(time.time())

async def init_db():
    """
    Initialise la DB en exécutant init_db.sql si présent.
    """
    BASE_DIR = Path(__file__).resolve().parents[2]
    SCHEMA_PATH = BASE_DIR / "init_db.sql"

    if not SCHEMA_PATH.exists():
        print(f"[DB] init_db.sql introuvable ({SCHEMA_PATH}), skipping automatic init.")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        await db.executescript(sql)
        await db.commit()
    print(f"[DB] Initialisation effectuée ({DB_PATH}).")


# ---- Settings helpers -----------------------------------------------------
async def get_setting(key: str, default=None, cast=None):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = await cur.fetchone()
            if not row:
                return default
            val = row[0]
            if cast:
                try:
                    return cast(val)
                except Exception:
                    return default
            return val
    except Exception as e:
        print(f"[DB] get_setting({key}) failed: {e}")
        return default

async def set_setting(key: str, value):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
            await db.commit()
    except Exception as e:
        print(f"[DB] set_setting({key}) failed: {e}")

# ---- Users / sessions -----------------------------------------------------
async def upsert_user(user_id: int, username: str, join_date: int = None):
    join_date = join_date or now_ts()
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, username, join_date)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
                """,
                (user_id, username, join_date),
            )
            await db.commit()
    except Exception as e:
        print(f"[DB] upsert_user({user_id}) failed: {e}")

async def get_user(user_id: int, guild_id: int = None):
    """
    Retourne un dict minimal avec champs usuels si présent, sinon None.
    Ne jette pas en cas d'erreur.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT total_time, total_A, total_B, sessions_count, streak_current, streak_best FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "total_time": row[0] or 0,
                "total_A": row[1] or 0,
                "total_B": row[2] or 0,
                "sessions_count": row[3] or 0,
                "streak_current": row[4] or 0,
                "streak_best": row[5] or 0,
            }
    except Exception as e:
        print(f"[DB] get_user({user_id}) failed: {e}")
        return None

# ---- Participants table helpers -------------------------------------------
async def add_participant(guild_id: int, user_id: int, mode: str) -> bool:
    """
    Ajoute un participant si non présent. Retourne True si ajouté, False si déjà présent.
    """
    ts = now_ts()
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # table participants peut être (guild_id, user_id, join_ts, mode, validated)
            try:
                cur = await db.execute(
                    "SELECT 1 FROM participants WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                if await cur.fetchone():
                    return False
                await db.execute(
                    "INSERT INTO participants (guild_id, user_id, join_ts, mode, validated) VALUES (?, ?, ?, ?, ?)",
                    (guild_id, user_id, ts, mode, 0),
                )
                await db.commit()
                return True
            except Exception:
                # fallback ancien schéma sans guild_id: (user_id, join_ts, mode, validated)
                cur = await db.execute("SELECT 1 FROM participants WHERE user_id=?", (user_id,))
                if await cur.fetchone():
                    return False
                await db.execute(
                    "INSERT INTO participants (user_id, join_ts, mode, validated) VALUES (?, ?, ?, ?)",
                    (user_id, ts, mode, 0),
                )
                await db.commit()
                return True
    except Exception as e:
        print(f"[DB] add_participant({guild_id},{user_id}) failed: {e}")
        return False

async def get_participants(guild_id: int):
    """
    Retourne une liste de tuples (user_id, join_ts, mode, validated).
    Si la table/colonne manque, renvoie [] mais logge.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # essayer le schéma récent
            try:
                cur = await db.execute("SELECT user_id, join_ts, mode, validated FROM participants WHERE guild_id=?", (guild_id,))
                rows = await cur.fetchall()
                return rows or []
            except Exception:
                # fallback ancienne table sans guild_id
                cur = await db.execute("SELECT user_id, join_ts, mode, validated FROM participants")
                rows = await cur.fetchall()
                # filtrer ceux qui appartiennent à la guild si on ne peut pas savoir => renvoyer tous (sécurité: caller traitera)
                return rows or []
    except Exception as e:
        print(f"[DB] get_participants({guild_id}) failed: {e}")
        return []

async def remove_participant(guild_id: int, user_id: int):
    """
    Supprime et retourne (join_ts, mode) si trouvé ; sinon retourne None.
    Gère schéma avec ou sans guild_id.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # try recent schema
            try:
                cur = await db.execute("SELECT join_ts, mode FROM participants WHERE guild_id=? AND user_id=?", (guild_id, user_id))
                row = await cur.fetchone()
                if not row:
                    # fallback: try without guild
                    cur = await db.execute("SELECT join_ts, mode FROM participants WHERE user_id=?", (user_id,))
                    row = await cur.fetchone()
                if not row:
                    return None
                # delete any matching rows
                try:
                    await db.execute("DELETE FROM participants WHERE guild_id=? AND user_id=?", (guild_id, user_id))
                except Exception:
                    await db.execute("DELETE FROM participants WHERE user_id=?", (user_id,))
                await db.commit()
                return (row[0], row[1])
            except Exception:
                # fallback simple
                cur = await db.execute("SELECT join_ts, mode FROM participants WHERE user_id=?", (user_id,))
                row = await cur.fetchone()
                if not row:
                    return None
                await db.execute("DELETE FROM participants WHERE user_id=?", (user_id,))
                await db.commit()
                return (row[0], row[1])
    except Exception as e:
        print(f"[DB] remove_participant({guild_id},{user_id}) failed: {e}")
        return None

# ---- Time aggregation (ajouter_temps) ------------------------------------
async def ajouter_temps(user_id: int, guild_id: int, elapsed: int, mode: str = "A", is_session_end: bool = False):
    """
    Ajoute du temps à l'utilisateur. Cette fonction tente de mettre à jour
    la table users avec différents noms de colonnes selon le schéma.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # essayer mise à jour colonnes attendues
            try:
                # assurer existence row
                cur = await db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
                if not await cur.fetchone():
                    await db.execute("INSERT INTO users (user_id, username, join_date) VALUES (?, ?, ?)", (user_id, "", now_ts()))
                # increment total_time
                await db.execute("UPDATE users SET total_time = COALESCE(total_time,0) + ? WHERE user_id=?", (elapsed, user_id))
                if mode == "A":
                    await db.execute("UPDATE users SET total_A = COALESCE(total_A,0) + ? WHERE user_id=?", (elapsed, user_id))
                else:
                    await db.execute("UPDATE users SET total_B = COALESCE(total_B,0) + ? WHERE user_id=?", (elapsed, user_id))
                if is_session_end:
                    # increment sessions_count if column exists
                    try:
                        await db.execute("UPDATE users SET sessions_count = COALESCE(sessions_count,0) + 1 WHERE user_id=?", (user_id,))
                    except Exception:
                        pass
                await db.commit()
                return True
            except Exception:
                # fallback minimal: try a generic time column
                try:
                    await db.execute("UPDATE users SET total_time = COALESCE(total_time,0) + ? WHERE user_id=?", (elapsed, user_id))
                    await db.commit()
                    return True
                except Exception:
                    return False
    except Exception as e:
        print(f"[DB] ajouter_temps({user_id}) failed: {e}")
        return False

# ---- Stickies (déjà discuté) ---------------------------------------------
async def set_sticky(guild_id: int, channel_id: int, message_id: int, content: str, author_id: int):
    """
    Remplace le sticky pour le salon donné (garantit 1 sticky par salon).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("DELETE FROM stickies WHERE guild_id=? AND channel_id=?", (guild_id, channel_id))
        except Exception:
            pass
        try:
            await db.execute("DELETE FROM stickies WHERE channel_id=?", (channel_id,))
        except Exception:
            pass

        try:
            await db.execute(
                "INSERT INTO stickies (guild_id, channel_id, message_id, content, author_id) VALUES (?, ?, ?, ?, ?)",
                (guild_id, channel_id, message_id, content, author_id),
            )
        except Exception:
            try:
                await db.execute(
                    "INSERT OR REPLACE INTO stickies (channel_id, message_id, text, requested_by) VALUES (?, ?, ?, ?)",
                    (channel_id, message_id, content, author_id),
                )
            except Exception as e:
                print(f"[DB] set_sticky fallback insert failed: {e}")
        await db.commit()

async def get_sticky(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cur = await db.execute("SELECT message_id, content, author_id FROM stickies WHERE guild_id=? AND channel_id=?", (guild_id, channel_id))
            r = await cur.fetchone()
            if r:
                return r
        except Exception:
            pass
        try:
            cur = await db.execute("SELECT message_id, text, requested_by FROM stickies WHERE channel_id=?", (channel_id,))
            return await cur.fetchone()
        except Exception:
            return None

async def remove_sticky(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("DELETE FROM stickies WHERE guild_id=? AND channel_id=?", (guild_id, channel_id))
        except Exception:
            pass
        try:
            await db.execute("DELETE FROM stickies WHERE channel_id=?", (channel_id,))
        except Exception:
            pass
        await db.commit()

# ---- Leaderboards & stats (basic safe implementations) --------------------
async def get_leaderboards(guild_id: int):
    """
    Retourne un dictionnaire de classements. Implémentation sûre, retourne vide si tables manquent.
    Format : {title: [(user_id, value), ...], ...}
    """
    lbs = {}
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Ex : top temps total
            try:
                cur = await db.execute("SELECT user_id, total_time FROM users ORDER BY total_time DESC LIMIT 10")
                rows = await cur.fetchall()
                lbs["Temps total"] = rows
            except Exception:
                lbs["Temps total"] = []
            # Ex : top sessions_count
            try:
                cur = await db.execute("SELECT user_id, sessions_count FROM users ORDER BY sessions_count DESC LIMIT 10")
                rows = await cur.fetchall()
                lbs["Sessions"] = rows
            except Exception:
                lbs["Sessions"] = []
    except Exception as e:
        print(f"[DB] get_leaderboards failed: {e}")
    return lbs

async def get_server_stats(guild_id: int):
    """
    Retourne un dict minimal pour stats serveur.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT COUNT(DISTINCT user_id) FROM users")
            users = (await cur.fetchone())[0] or 0
            cur = await db.execute("SELECT SUM(total_time) FROM users")
            total_time = (await cur.fetchone())[0] or 0
            avg_time = int(total_time / users) if users else 0
            return {"users": users, "total_time": total_time, "avg_time": avg_time}
    except Exception as e:
        print(f"[DB] get_server_stats failed: {e}")
        return {"users": 0, "total_time": 0, "avg_time": 0}

async def clear_all_stats(guild_id: int = None):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM users")
            await db.execute("DELETE FROM participants")
            await db.commit()
    except Exception as e:
        print(f"[DB] clear_all_stats failed: {e}")

async def get_active_session(guild_id: int, user_id: int):
    """
    Retourne (join_ts, mode) si session en cours, sinon None.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            try:
                cur = await db.execute("SELECT join_ts, mode FROM participants WHERE guild_id=? AND user_id=?", (guild_id, user_id))
                row = await cur.fetchone()
                if row:
                    return (row[0], row[1])
            except Exception:
                cur = await db.execute("SELECT join_ts, mode FROM participants WHERE user_id=?", (user_id,))
                return await cur.fetchone()
    except Exception as e:
        print(f"[DB] get_active_session failed: {e}")
    return None
