# ==========================
# LRE-BOT/src/utils/checks.py
# ==========================
from discord.ext import commands
from core import db


def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)


def in_pomodoro_channel():
    async def predicate(ctx):
        # Vérifications de base
        if ctx.guild is None or ctx.channel is None:
            raise commands.CheckFailure("NO_POMODORO_CHANNEL")

        guild_id = ctx.guild.id

        # Essayer la clé par-guild d'abord, puis fallback sur une clé globale historique
        pomodoro_channel_id = await db.get_setting(f"pomodoro_channel_{guild_id}", default=None, cast=int)
        if pomodoro_channel_id is None:
            pomodoro_channel_id = await db.get_setting("channel_id", default=None, cast=int)

        if pomodoro_channel_id and ctx.channel.id == pomodoro_channel_id:
            return True

        raise commands.CheckFailure("NO_POMODORO_CHANNEL")
    return commands.check(predicate)


def roles_are_set():
    async def predicate(ctx):
        if ctx.guild is None:
            raise commands.CheckFailure("NO_POMODORO_ROLES")

        guild_id = ctx.guild.id

        # On supporte plusieurs conventions de clé (par-guild puis global)
        role_a = await db.get_setting(f"role_A_{guild_id}", default=None, cast=int)
        role_b = await db.get_setting(f"role_B_{guild_id}", default=None, cast=int)

        if role_a is None:
            role_a = await db.get_setting("pomodoro_role_A", default=None, cast=int)
        if role_b is None:
            role_b = await db.get_setting("pomodoro_role_B", default=None, cast=int)

        if role_a and role_b:
            return True

        raise commands.CheckFailure("NO_POMODORO_ROLES")
    return commands.check(predicate)


def not_in_maintenance():
    async def predicate(ctx):
        # Si on est en guild : utiliser la fonction dédiée (stocke maintenance_{guild_id})
        if ctx.guild is not None:
            is_maint = await db.get_maintenance(ctx.guild.id)
            return not is_maint

        # Fallback pour DM / contexte sans guild
        val = await db.get_setting("maintenance", default="0")
        return val != "1"
    return commands.check(predicate)
