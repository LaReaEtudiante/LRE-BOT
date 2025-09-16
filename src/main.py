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

# Charger les cogs
initial_cogs = [
    "cogs.admin",
    "cogs.user",
    "cogs.pomodoro",
    "cogs.sticky",
    "cogs.events"
]

for cog in initial_cogs:
    bot.load_extension(cog)

bot.run(config.TOKEN)
