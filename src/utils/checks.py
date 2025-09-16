# ==========================
# LRE-BOT/src/utils/checks.py
# ==========================
from discord.ext import commands

def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)
