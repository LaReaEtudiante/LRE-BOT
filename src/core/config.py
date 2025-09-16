# ==========================
# LRE-BOT/src/core/config.py
# ==========================
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("DB_PATH", "data/bot.db")
RESET_HOUR = int(os.getenv("RESET_HOUR", 0))
TIMEZONE = os.getenv("TIMEZONE", "Europe/Zurich")

