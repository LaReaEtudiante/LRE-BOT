# ==========================
# LRE-BOT/src/main.py
# ==========================
import discord
from discord.ext import commands
from pathlib import Path
from core import config
import logging

# ─── Configuration du logging ────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger('LRE-BOT')

# ─── Vérifications & préparation du dossier DB ──────────────
Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# ─── Intents Discord ─────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# ─── Création du bot avec classe personnalisée ──────────────
class LREBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="*",
            help_command=None,
            intents=intents
        )
    
    async def setup_hook(self):
        """Chargement automatique des Cogs au démarrage"""
        initial_cogs = ["cogs.admin", "cogs.user", "cogs.pomodoro", "cogs.events"]
        
        logger.info("Démarrage du bot LRE...")
        
        for cog in initial_cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"[COG] ✅ {cog} chargé")
            except Exception as e:
                logger.error(f"[COG] ❌ Erreur lors du chargement de {cog} : {e}")
                import traceback
                traceback.print_exc()
        
        logger.info("Tous les Cogs ont été traités.")

# ─── Création de l'instance du bot ──────────────────────────
bot = LREBot()

# ─── Vérification du token ───────────────────────────────────
if not config.TOKEN:
    raise ValueError("❌ Le token Discord est introuvable. Vérifie ton fichier .env !")

# ─── Lancement du bot ────────────────────────────────────────
if __name__ == "__main__":
    logger.info("Initialisation...")
    bot.run(config.TOKEN)
