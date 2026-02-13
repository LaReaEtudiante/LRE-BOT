# ==========================
# LRE-BOT/src/utils/checks.py
# ==========================
from discord.ext import commands
from core import db


def not_in_maintenance():
    """Décorateur pour bloquer les commandes en mode maintenance"""
    async def predicate(ctx):
        is_maint = await db.is_maintenance_active(ctx.guild.id)
        if is_maint:
            raise commands.CheckFailure("MAINTENANCE_ACTIVE")
        return True
    return commands.check(predicate)
