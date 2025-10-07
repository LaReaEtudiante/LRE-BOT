# src/main.py
import discord
from discord.ext import commands
from core import config

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="*", help_command=None, intents=intents)

async def _setup_hook():
    initial_cogs = ["cogs.admin", "cogs.user", "cogs.pomodoro", "cogs.events"]
    for cog in initial_cogs:
        await bot.load_extension(cog)
    print("[INFO] Tous les cogs ont été chargés avec succès.")

bot.setup_hook = _setup_hook  # ← important

if config.TOKEN is None:
    raise ValueError("❌ Le token Discord est introuvable. Vérifie ton fichier .env !")

bot.run(config.TOKEN)
