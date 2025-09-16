# ==========================
# LRE-BOT/src/core/logger.py
# ==========================
import logging

logger = logging.getLogger("lre-bot")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
