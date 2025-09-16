# ==========================
# LRE-BOT/src/main.py
# ==========================
import discord
from discord.ext import commands
from core import config

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="*", intents=intents)

# Charger les cogs au démarrage
@bot.event
async def setup_hook():
    initial_cogs = [
        "cogs.admin",
        "cogs.user",
        "cogs.pomodoro",
        "cogs.sticky",
        "cogs.events"
    ]
    for cog in initial_cogs:
        await bot.load_extension(cog)
    print("[INFO] Tous les cogs ont été chargés avec succès.")

# Lancer le bot
if config.TOKEN is None:
    raise ValueError("❌ Le token Discord est introuvable. Vérifie ton fichier .env !")

bot.run(config.TOKEN)
