# ==========================
# LRE-BOT/src/core/db.py
# ==========================
import aiosqlite
import os

DB_PATH = os.getenv("DB_PATH", "data/bot.db")

async def init_db():
    """Créer les tables si elles n'existent pas déjà."""
    async with aiosqlite.connect(DB_PATH) as db:
        with open("init_db.sql", "r", encoding="utf-8") as f:
            await db.executescript(f.read())
        await db.commit()

async def get_db():
    """Retourne une connexion à la DB (à fermer manuellement)."""
    return await aiosqlite.connect(DB_PATH)
