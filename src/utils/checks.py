# ==========================
# LRE-BOT/src/utils/checks.py
# ==========================
from discord.ext import commands
from core import config

def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

def in_pomodoro_channel():
    async def predicate(ctx):
        pomodoro_channel_id = config.get_pomodoro_channel(ctx.guild.id)
        return ctx.channel and ctx.channel.id == pomodoro_channel_id
    return commands.check(predicate)

def roles_are_set():
    async def predicate(ctx):
        guild_id = ctx.guild.id
        role_a = config.get_role_a(guild_id)
        role_b = config.get_role_b(guild_id)
        return role_a is not None and role_b is not None
    return commands.check(predicate)

def not_in_maintenance():
    async def predicate(ctx):
        return not config.is_in_maintenance(ctx.guild.id)
    return commands.check(predicate)
