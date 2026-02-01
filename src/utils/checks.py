# ==========================
# LRE-BOT/src/utils/checks.py
# ==========================
from discord.ext import commands
import discord
from core import db


def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)


def in_pomodoro_channel():
    async def predicate(ctx):
        if ctx.guild is None or ctx.channel is None:
            raise commands.CheckFailure("NO_POMODORO_CHANNEL")

        guild_id = ctx.guild.id

        pomodoro_channel_id = await db.get_setting(f"pomodoro_channel_{guild_id}", default=None)
        if pomodoro_channel_id is None:
            pomodoro_channel_id = await db.get_setting("channel_id", default=None)

        if pomodoro_channel_id is None:
            raise commands.CheckFailure("NO_POMODORO_CHANNEL")

        try:
            if int(pomodoro_channel_id) == ctx.channel.id:
                return True
        except Exception:
            # stored value not an int or mismatch — fallthrough to failure
            pass

        raise commands.CheckFailure("NO_POMODORO_CHANNEL")
    return commands.check(predicate)


def roles_are_set():
    async def predicate(ctx):
        if ctx.guild is None:
            raise commands.CheckFailure("NO_POMODORO_ROLES")
        guild_id = ctx.guild.id

        # Lire les valeurs (peuvent être ID stocké comme string ou nom)
        role_a_val = await db.get_setting(f"role_A_{guild_id}", default=None)
        role_b_val = await db.get_setting(f"role_B_{guild_id}", default=None)

        if role_a_val is None:
            role_a_val = await db.get_setting("pomodoro_role_A", default=None)
        if role_b_val is None:
            role_b_val = await db.get_setting("pomodoro_role_B", default=None)

        def resolve_role(val):
            if not val:
                return None
            # Essayer par ID si possible
            try:
                rid = int(str(val))
                role = ctx.guild.get_role(rid)
                if role:
                    return role
            except Exception:
                pass
            # Sinon essayer par nom
            return discord.utils.get(ctx.guild.roles, name=val)

        role_a = resolve_role(role_a_val)
        role_b = resolve_role(role_b_val)

        if role_a and role_b:
            return True

        raise commands.CheckFailure("NO_POMODORO_ROLES")
    return commands.check(predicate)


def not_in_maintenance():
    async def predicate(ctx):
        if ctx.guild is not None:
            is_maint = await db.get_maintenance(ctx.guild.id)
            if is_maint:
                # CheckFailure spécifique (géré dans on_command_error)
                raise commands.CheckFailure("MAINTENANCE_ACTIVE")
            return True

        # Fallback pour DM / contexte sans guild
        val = await db.get_setting("maintenance", default="0")
        if val == "1":
            raise commands.CheckFailure("MAINTENANCE_ACTIVE")
        return True
    return commands.check(predicate)
