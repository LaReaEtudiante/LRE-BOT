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
BASE_DIR = Path(__file__).resolve().parents[2]
SCHEMA_PATH = BASE_DIR / "init_db.sql"


def now_ts() -> int:
    return int(time.time())


async def init_db():
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"init_db.sql introuvable: {SCHEMA_PATH}")

    async with aiosqlite.connect(DB_PATH) as db:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            sql_script = f.read()
        await db.executescript(sql_script)
        await db.commit()
        print(f"[DB] Initialisation OK → {DB_PATH}")


# --- exemples d'autres fonctions (inchangées) ---
# upsert_user, get_user, add_participant, remove_participant, etc.
# (garde le reste de ton fichier tel quel)
# -------------------------------------------------------------------
# Ci‑dessous : parties STICKIES modifiées pour garantir 1 sticky par salon
# -------------------------------------------------------------------

async def set_sticky(guild_id: int, channel_id: int, message_id: int, content: str, author_id: int):
    """
    Crée ou remplace le sticky pour le salon donné.
    Avant insertion on supprime toute ligne existante pour channel_id (et/ou guild+channel)
    pour garantir qu'il n'y ait qu'un sticky par salon.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Nettoyer toute ancienne entrée pour ce channel (couverture des deux schémas possibles)
        try:
            await db.execute("DELETE FROM stickies WHERE guild_id=? AND channel_id=?", (guild_id, channel_id))
        except Exception:
            pass
        try:
            await db.execute("DELETE FROM stickies WHERE channel_id=?", (channel_id,))
        except Exception:
            pass

        # Essayer d'insérer dans le schéma récent (guild_id, channel_id, message_id, content, author_id)
        try:
            await db.execute(
                """
                INSERT INTO stickies (guild_id, channel_id, message_id, content, author_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, channel_id, message_id, content, author_id),
            )
        except (sqlite3.OperationalError, Exception):
            # Fallback pour ancien schéma (channel_id, message_id, text, requested_by)
            try:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO stickies (channel_id, message_id, text, requested_by)
                    VALUES (?, ?, ?, ?)
                    """,
                    (channel_id, message_id, content, author_id),
                )
            except Exception:
                # si tout échoue, on laisse tomber silencieusement (appelant doit logger)
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
            if row:
                return row
        except Exception:
            pass

        # Fallback sur ancien schéma (sans guild_id)
        try:
            cur = await db.execute(
                "SELECT message_id, text, requested_by FROM stickies WHERE channel_id=?",
                (channel_id,),
            )
            return await cur.fetchone()
        except Exception:
            return None


async def remove_sticky(guild_id: int, channel_id: int):
    """
    Supprime le sticky pour le salon donné.
    Tente la suppression par guild+channel puis fallback par channel seul.
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

        await db.commit()
