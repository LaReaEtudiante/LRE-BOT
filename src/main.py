# ==========================
# LRE-BOT/src/main.py
# ==========================
import discord
from discord.ext import commands
from pathlib import Path
from core import config
import logging
import os
import sys
import traceback

# ─── Configuration du logging ────────────────────────────────
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter(
    '[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()
root_logger.addHandler(handler)

logger = logging.getLogger('LRE-BOT')

logger.info(f"🚀 DÉMARRAGE MAIN.PY - PID={os.getpid()}")

# ─── Vérifications & préparation du dossier DB ──────────────
try:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    logger.info("✅ Configuration des répertoires de base de données OK")
except Exception as e:
    logger.error(f"❌ Erreur lors de la création du dossier DB: {e}")
    sys.exit(1)

# ─── Intents Discord ─────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
logger.info("✅ Intents Discord configurés")

# ─── Création du bot avec classe personnalisée ──────────────
class LREBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="*",
            help_command=None,
            intents=intents
        )
        logger.info("✅ Instance LREBot initialisée")

    async def setup_hook(self):
        """Chargement automatique des Cogs au démarrage"""
        logger.info("⏳ Chargement des extensions (Cogs)...")
        
        initial_cogs = ["cogs.admin", "cogs.user", "cogs.pomodoro", "cogs.events"]
        cogs_loaded = 0

        for cog in initial_cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"✅ Extension chargée : {cog}")
                cogs_loaded += 1
            except Exception as e:
                logger.error(f"❌ Erreur critique lors du chargement de l'extension {cog} : {e}")
                logger.error("Traceback complet :")
                traceback.print_exc()

        logger.info(f"✅ {cogs_loaded}/{len(initial_cogs)} extensions chargées avec succès.")

# ─── Vérification du token ───────────────────────────────────
if not config.TOKEN:
    logger.error("❌ Le token Discord est introuvable. Vérifie ton fichier .env !")
    sys.exit(1)
else:
    logger.info("✅ Token Discord détecté")

# ─── Lancement du bot ────────────────────────────────────────
bot = LREBot()

if __name__ == "__main__":
    try:
        logger.info("⏳ Connexion aux serveurs Discord...")
        bot.run(config.TOKEN)
    except Exception as e:
        logger.error(f"❌ Erreur fatale lors du lancement de bot.run: {e}")
        traceback.print_exc()

