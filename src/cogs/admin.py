# ==========================
# LRE-BOT/src/cogs/admin.py
# ==========================
import discord
from discord.ext import commands
from datetime import datetime, timezone
import asyncio
import subprocess

from core import db
from utils.time_format import format_seconds

POMO_ROLE_A = "Mode A"
POMO_ROLE_B = "Mode B"


# ─── CHECKS ───────────────────────────────────────────────

def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)


# ─── STATUS ───────────────────────────────────────────────

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="status", help="Afficher état global du bot")
    @is_admin()
    async def status(self, ctx):
        latency = round(self.bot.latency * 1000)
        now_utc = datetime.now(timezone.utc)
        local_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

        guild_id = ctx.guild.id

        # Participants
        participants = await db.get_participants(guild_id)
        countA = len([p for p in participants if p[2] == "A"])
        countB = len([p for p in participants if p[2] == "B"])

        # Salon Pomodoro
        pomodoro_channel_id = await db.get_setting(f"pomodoro_channel_{guild_id}")
        chan = ctx.guild.get_channel(int(pomodoro_channel_id)) if pomodoro_channel_id else None
        chan_field = f"✅ {chan.mention}" if chan else "❌ non configuré"

        # Rôles
        roleA_name = await db.get_setting(f"role_A_{guild_id}", POMO_ROLE_A)
        roleB_name = await db.get_setting(f"role_B_{guild_id}", POMO_ROLE_B)

        roleA = discord.utils.get(ctx.guild.roles, name=roleA_name)
        roleB = discord.utils.get(ctx.guild.roles, name=roleB_name)

        roleA_field = f"✅ {roleA.mention}" if roleA else "❌ non configuré"
        roleB_field = f"✅ {roleB.mention}" if roleB else "❌ non configuré"

        # Git SHA
        proc = await asyncio.create_subprocess_shell(
            "git rev-parse --short HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await proc.communicate()
        sha = out.decode().strip() if out else "unknown"

        e = discord.Embed(title="⚙️ État du bot", color=discord.Color.blue())
        e.add_field(name="Latence", value=f"{latency} ms", inline=True)
        e.add_field(name="Heure", value=local_str, inline=True)
        e.add_field(name="Mode A", value=f"{countA} participants", inline=True)
        e.add_field(name="Mode B", value=f"{countB} participants", inline=True)
        e.add_field(name="Salon Pomodoro", value=chan_field, inline=False)
        e.add_field(name="Rôle A", value=roleA_field, inline=True)
        e.add_field(name="Rôle B", value=roleB_field, inline=True)
        e.add_field(name="Version (SHA)", value=sha, inline=True)

        await ctx.send(embed=e)


    # ─── MAINTENANCE ──────────────────────────────────────

    @commands.command(name="maintenance", help="Activer ou désactiver le mode maintenance")
    @is_admin()
    async def maintenance(self, ctx):
        guild_id = ctx.guild.id
        enabled = not await db.get_maintenance(guild_id)
        await db.set_maintenance(guild_id, enabled)

        if enabled:
            # Stopper toutes les sessions
            participants = await db.get_participants(guild_id)
            now_ts = int(datetime.now(timezone.utc).timestamp())
            for user_id, join_ts, mode, _ in participants:
                elapsed = now_ts - join_ts
                await db.ajouter_temps(user_id, guild_id, elapsed, mode=mode, is_session_end=True)

            await ctx.send("🚧 Mode maintenance activé. Toutes les sessions ont été arrêtées.")
        else:
            await ctx.send("✅ Mode maintenance désactivé.")


    # ─── CONFIG SALON ─────────────────────────────────────

    @commands.command(name="defs", help="Définir le salon Pomodoro")
    @is_admin()
    async def defs(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        await db.set_setting(f"pomodoro_channel_{ctx.guild.id}", str(channel.id))

        e = discord.Embed(
            title="⚙️ Configuration mise à jour",
            description=f"Le salon Pomodoro est maintenant {channel.mention}.",
            color=discord.Color.green()
        )
        await ctx.send(embed=e)


    # ─── CONFIG RÔLE A ────────────────────────────────────

    @commands.command(name="defa", help="Définir ou créer le rôle Pomodoro A")
    @is_admin()
    async def defa(self, ctx, *, role_name: str = None):
        guild_id = ctx.guild.id
        role_name = role_name or POMO_ROLE_A

        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if not role:
            role = await ctx.guild.create_role(name=role_name, colour=discord.Colour(0x206694))

        await db.set_setting(f"role_A_{guild_id}", role.name)

        e = discord.Embed(
            title="⚙️ Configuration mise à jour",
            description=f"Le rôle Pomodoro A est {role.mention}.",
            color=discord.Color.green()
        )
        await ctx.send(embed=e)


    # ─── CONFIG RÔLE B ────────────────────────────────────

    @commands.command(name="defb", help="Définir ou créer le rôle Pomodoro B")
    @is_admin()
    async def defb(self, ctx, *, role_name: str = None):
        guild_id = ctx.guild.id
        role_name = role_name or POMO_ROLE_B

        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if not role:
            role = await ctx.guild.create_role(name=role_name, colour=discord.Colour(0x206694))

        await db.set_setting(f"role_B_{guild_id}", role.name)

        e = discord.Embed(
            title="⚙️ Configuration mise à jour",
            description=f"Le rôle Pomodoro B est {role.mention}.",
            color=discord.Color.green()
        )
        await ctx.send(embed=e)


    # ─── COLLE (sticky message) ───────────────────────────

    @commands.command(name="colle", help="Créer un sticky message")
    @is_admin()
    async def colle(self, ctx, *, message: str):
        guild_id = ctx.guild.id
        channel_id = ctx.channel.id

        # Supprimer l'ancien sticky
        existing = await db.get_sticky(guild_id, channel_id)
        if existing:
            try:
                old_msg = await ctx.channel.fetch_message(existing[0])  # message_id
                await old_msg.delete()
            except Exception:
                pass
            await db.remove_sticky(guild_id, channel_id)

        # Envoyer le nouveau sticky
        sticky_msg = await ctx.send(message)
        await db.set_sticky(guild_id, channel_id, sticky_msg.id, message, ctx.author.id)

        try:
            await ctx.message.delete()
        except Exception:
            pass


    # ─── CLEAR STATS ─────────────────────────────────────

    @commands.command(name="clear_stats", help="Réinitialiser toutes les stats")
    @is_admin()
    async def clear_stats(self, ctx):
        await db.clear_all_stats(ctx.guild.id)

        e = discord.Embed(
            title="🗑 Réinitialisation effectuée",
            description="Toutes les statistiques ont été remises à zéro.",
            color=discord.Color.red()
        )
        await ctx.send(embed=e)


    # ─── UPDATE ──────────────────────────────────────────

    @commands.command(name="update", help="Mettre à jour et redémarrer le bot")
    @is_admin()
    async def update(self, ctx):
        await ctx.send("♻️ Mise à jour lancée, le bot va redémarrer...")
        try:
            subprocess.Popen(["/home/marc/bin/deploy-lre"])
        except Exception as e:
            await ctx.send(f"❌ Erreur lors du déploiement : {e}")


# ─── SETUP ───────────────────────────────────────────────

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
