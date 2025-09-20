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
        pomodoro_channel_id = await db.get_setting("channel_id", default=None)
        if ctx.channel and str(ctx.channel.id) == str(pomodoro_channel_id):
            return True
        raise commands.CheckFailure("NO_POMODORO_CHANNEL")
    return commands.check(predicate)


def roles_are_set():
    async def predicate(ctx):
        role_a = await db.get_setting("pomodoro_role_A", default=None)
        role_b = await db.get_setting("pomodoro_role_B", default=None)
        if role_a and role_b:
            return True
        raise commands.CheckFailure("NO_POMODORO_ROLES")
    return commands.check(predicate)


def not_in_maintenance():
    async def predicate(ctx):
        val = await db.get_setting("maintenance", default="0")
        return val != "1"
    return commands.check(predicate)
