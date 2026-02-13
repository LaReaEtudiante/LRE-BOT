# ==========================
# LRE-BOT/src/utils/checks.py
# ==========================
from discord.ext import commands
from core import db


def is_admin():
    """Vérifier si l'utilisateur est administrateur"""
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)


def not_in_maintenance():
    """Décorateur pour bloquer les commandes en mode maintenance"""
    async def predicate(ctx):
        if ctx.guild is not None:
            is_maint = await db.is_maintenance_active(ctx.guild.id)
            if is_maint:
                raise commands.CheckFailure("MAINTENANCE_ACTIVE")
        return True
    return commands.check(predicate)
