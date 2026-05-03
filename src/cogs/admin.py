# ==========================
# LRE-BOT/src/cogs/admin.py
# ==========================
import discord
from discord.ext import commands
from datetime import datetime, timezone
import asyncio
from utils import checks
import logging

from core import db
from utils.time_format import format_seconds

logger = logging.getLogger('LRE-BOT.admin')

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="status", help="Afficher état global du bot")
    @checks.is_admin()
    async def status(self, ctx):
        latency = round(self.bot.latency * 1000)
        now_utc = datetime.now(timezone.utc)
        local_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

        guild_id = ctx.guild.id

        # Participants
        participants = await db.get_participants(guild_id)
        countA = len([p for p in participants if p[2] == "A"])
        countB = len([p for p in participants if p[2] == "B"])

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
        e.add_field(name="Version (SHA)", value=sha, inline=True)

        await ctx.send(embed=e)


    @commands.command(name="maintenance", help="Activer ou désactiver le mode maintenance")
    @checks.is_admin()
    async def maintenance(self, ctx):
        guild_id = ctx.guild.id
        enabled = not await db.get_maintenance(guild_id)
        await db.set_maintenance(guild_id, enabled)

        if enabled:
            logger.warning(f"🚧 Mode maintenance activé par {ctx.author}")
            participants = await db.get_participants(guild_id)
            now_ts = int(datetime.now(timezone.utc).timestamp())

            # si participants présents = une seule notif listant les mentions
            if participants:
                mentions = " ".join(f"<@{user_id}>" for user_id, _, _, _ in participants)
                notif_msg = f"🚧 Mode maintenance activé — toutes les sessions ont été arrêtées.\nParticipants retirés : {mentions}"
                await ctx.send(notif_msg)

            # archiver et supprimer
            for user_id, join_ts, mode, _ in participants:
                elapsed = now_ts - join_ts
                await db.ajouter_temps(user_id, guild_id, elapsed, mode=mode, is_session_end=True)
                try:
                    await db.remove_participant(guild_id, user_id)
                except Exception:
                    pass

            if not participants:
                await ctx.send("🚧 Mode maintenance activé. Aucune session en cours.")
        else:
            logger.info(f"✅ Mode maintenance désactivé par {ctx.author}")
            await ctx.send("✅ Mode maintenance désactivé.")


    @commands.command(name="colle", help="Créer un sticky message")
    @checks.is_admin()
    async def colle(self, ctx, *, message: str):
        guild_id = ctx.guild.id
        channel_id = ctx.channel.id

        existing = await db.get_sticky(guild_id, channel_id)
        if existing:
            try:
                old_msg = await ctx.channel.fetch_message(existing[0])  # message_id
                await old_msg.delete()
            except Exception:
                pass
            await db.remove_sticky(guild_id, channel_id)

        sticky_msg = await ctx.send(message)
        try:
            await db.set_sticky(guild_id, channel_id, sticky_msg.id, message, ctx.author.id)
            logger.info(f"✅ Sticky message créé par {ctx.author} dans {ctx.channel.name}")
        except Exception as e:
            logger.error(f"❌ Échec sauvegarde sticky en DB: {e}")
            await ctx.send("⚠️ Échec lors de l'enregistrement du sticky en base de données.")
            return

        try:
            await ctx.message.delete()
        except Exception:
            pass

        await ctx.send("✅ Sticky créé et enregistré.")


    @commands.command(name="decoller", help="Retirer un sticky message")
    @checks.is_admin()
    async def decoller(self, ctx):
        guild_id = ctx.guild.id
        channel_id = ctx.channel.id

        existing = await db.get_sticky(guild_id, channel_id)
        if not existing:
            await ctx.send("ℹ️ Aucun sticky défini pour ce salon.")
            return

        try:
            old_msg = await ctx.channel.fetch_message(existing[0])
            await old_msg.delete()
        except Exception:
            pass

        await db.remove_sticky(guild_id, channel_id)
        logger.info(f"✅ Sticky message retiré par {ctx.author} dans {ctx.channel.name}")
        await ctx.send("✅ Sticky retiré.")


    @commands.command(name="clear_stats", help="Réinitialiser toutes les stats")
    @checks.is_admin()
    async def clear_stats(self, ctx):
        await db.clear_all_stats(ctx.guild.id)
        logger.warning(f"⚠️ Statistiques réinitialisées par {ctx.author}")

        e = discord.Embed(
            title="🗑 Réinitialisation effectuée",
            description="Toutes les statistiques ont été remises à zéro.",
            color=discord.Color.red()
        )
        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
