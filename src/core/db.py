# ==========================
# LRE-BOT/src/core/db.py
# ==========================
import aiosqlite
from core import config

async def init_db():
    async with aiosqlite.connect(config.DB_PATH) as db:
        with open("init_db.sql", "r", encoding="utf-8") as f:
            await db.executescript(f.read())
        await db.commit()
