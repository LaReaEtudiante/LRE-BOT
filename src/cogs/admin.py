# ==========================
# LRE-BOT/src/cogs/admin.py
# ==========================
import discord
from discord.ext import commands
from datetime import datetime, timezone
import asyncio
import subprocess
from utils import checks

from core import db
from utils.time_format import format_seconds

POMO_ROLE_A = "Mode A"
POMO_ROLE_B = "Mode B"

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

        # Salon Pomodoro (essayer clé par-guild puis global)
        pomodoro_channel_id = await db.get_setting(f"pomodoro_channel_{guild_id}", default=None)
        if pomodoro_channel_id is None:
            pomodoro_channel_id = await db.get_setting("channel_id", default=None)
        chan = ctx.guild.get_channel(int(pomodoro_channel_id)) if pomodoro_channel_id else None
        chan_field = f"✅ {chan.mention}" if chan else "❌ non configuré"

        # Rôles : on résout par ID stocké en DB (ou nom)
        roleA_val = await db.get_setting(f"role_A_{guild_id}", default=None)
        roleB_val = await db.get_setting(f"role_B_{guild_id}", default=None)

        if roleA_val is None:
            roleA_val = await db.get_setting("pomodoro_role_A", default=None)
        if roleB_val is None:
            roleB_val = await db.get_setting("pomodoro_role_B", default=None)

        def resolve_display(val):
            if not val:
                return "❌ non configuré"
            try:
                rid = int(str(val))
                role = ctx.guild.get_role(rid)
                if role:
                    return f"✅ {role.mention}"
            except Exception:
                pass
            role = discord.utils.get(ctx.guild.roles, name=val)
            if role:
                return f"✅ {role.mention}"
            return "❌ non configuré"

        roleA_field = resolve_display(roleA_val)
        roleB_field = resolve_display(roleB_val)

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


    @commands.command(name="maintenance", help="Activer ou désactiver le mode maintenance")
    @checks.is_admin()
    async def maintenance(self, ctx):
        guild_id = ctx.guild.id
        enabled = not await db.get_maintenance(guild_id)
        await db.set_maintenance(guild_id, enabled)

        if enabled:
            participants = await db.get_participants(guild_id)
            now_ts = int(datetime.now(timezone.utc).timestamp())

            # si participants présents = une seule notif listant les mentions
            if participants:
                pomodoro_channel_id = await db.get_setting(f"pomodoro_channel_{guild_id}", default=None)
                if pomodoro_channel_id is None:
                    pomodoro_channel_id = await db.get_setting("channel_id", default=None)
                channel = ctx.guild.get_channel(int(pomodoro_channel_id)) if pomodoro_channel_id else None

                mentions = " ".join(f"<@{user_id}>" for user_id, _, _, _ in participants)
                notif_msg = f"🚧 Mode maintenance activé — toutes les sessions ont été arrêtées.\nParticipants retirés : {mentions}"

                try:
                    if channel:
                        await channel.send(notif_msg)
                    else:
                        await ctx.send(notif_msg)
                except Exception:
                    pass

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
                # déjà notifié les participants
                pass
        else:
            await ctx.send("✅ Mode maintenance désactivé.")


    @commands.command(name="defs", help="Définir le salon Pomodoro")
    @checks.is_admin()
    async def defs(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        await db.set_setting(f"pomodoro_channel_{ctx.guild.id}", str(channel.id))

        e = discord.Embed(
            title="⚙️ Configuration mise à jour",
            description=f"Le salon Pomodoro est maintenant {channel.mention}.",
            color=discord.Color.green()
        )
        await ctx.send(embed=e)


    @commands.command(name="defa", help="Définir ou créer le rôle Pomodoro A")
    @checks.is_admin()
    async def defa(self, ctx, *, role_name: str = None):
        guild_id = ctx.guild.id
        default_name = "Mode A (50-10)"

        role = None
        if role_name:
            if ctx.message.role_mentions:
                role = ctx.message.role_mentions[0]
            else:
                try:
                    rid = int(role_name.strip().strip("<@&>").strip())
                    role = ctx.guild.get_role(rid)
                except Exception:
                    role = discord.utils.get(ctx.guild.roles, name=role_name)

        if not role:
            role = await ctx.guild.create_role(name=default_name, colour=discord.Colour(0x206694))

        await db.set_setting(f"role_A_{guild_id}", str(role.id))

        e = discord.Embed(
            title="⚙️ Configuration mise à jour",
            description=f"Le rôle Pomodoro A est {role.mention}.",
            color=discord.Color.green()
        )
        await ctx.send(embed=e)


    @commands.command(name="defb", help="Définir ou créer le rôle Pomodoro B")
    @checks.is_admin()
    async def defb(self, ctx, *, role_name: str = None):
        guild_id = ctx.guild.id
        default_name = "Mode B (25-5)"

        role = None
        if role_name:
            if ctx.message.role_mentions:
                role = ctx.message.role_mentions[0]
            else:
                try:
                    rid = int(role_name.strip().strip("<@&>").strip())
                    role = ctx.guild.get_role(rid)
                except Exception:
                    role = discord.utils.get(ctx.guild.roles, name=role_name)

        if not role:
            role = await ctx.guild.create_role(name=default_name, colour=discord.Colour(0x206694))

        await db.set_setting(f"role_B_{guild_id}", str(role.id))

        e = discord.Embed(
            title="⚙️ Configuration mise à jour",
            description=f"Le rôle Pomodoro B est {role.mention}.",
            color=discord.Color.green()
        )
        await ctx.send(embed=e)


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
        except Exception as e:
            print(f"[WARN] Échec sauvegarde sticky en DB: {e}")
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
        await ctx.send("✅ Sticky retiré.")


    @commands.command(name="clear_stats", help="Réinitialiser toutes les stats")
    @checks.is_admin()
    async def clear_stats(self, ctx):
        await db.clear_all_stats(ctx.guild.id)

        e = discord.Embed(
            title="🗑 Réinitialisation effectuée",
            description="Toutes les statistiques ont été remises à zéro.",
            color=discord.Color.red()
        )
        await ctx.send(embed=e)


    @commands.command(name="update", help="Mettre à jour et redémarrer le bot (désactivée)")
    @checks.is_admin()
    async def update(self, ctx):
        await ctx.send("❌ La commande `update` est désactivée sur ce serveur. Mettez à jour manuellement sur le serveur.")


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
