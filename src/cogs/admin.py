# ==========================
# LRE-BOT/src/cogs/admin.py
# ==========================
import discord
from discord.ext import commands
import asyncio
from datetime import datetime, timezone
from core import db
from utils import checks


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

        # Participants (si la fonction existe)
        try:
            participants = await db.get_participants(guild_id)
            countA = len([p for p in participants if p[2] == "A"])
            countB = len([p for p in participants if p[2] == "B"])
        except Exception:
            # si get_participants n'existe plus / échoue, on affiche NA
            countA = "N/A"
            countB = "N/A"

        # Salon Pomodoro (essayer clé par-guild puis global)
        pomodoro_channel_id = await db.get_setting(f"pomodoro_channel_{guild_id}", default=None)
        if pomodoro_channel_id is None:
            pomodoro_channel_id = await db.get_setting("channel_id", default=None)
        chan = None
        try:
            chan = ctx.guild.get_channel(int(pomodoro_channel_id)) if pomodoro_channel_id else None
        except Exception:
            chan = None
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

        # Git SHA (tentative)
        try:
            proc = await asyncio.create_subprocess_shell(
                "git rev-parse --short HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            out, _ = await proc.communicate()
            sha = out.decode().strip() if out else "unknown"
        except Exception:
            sha = "unknown"

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

    @commands.command(name="defa", help="Définir ou créer le rôle A")
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

    @commands.command(name="defb", help="Définir ou créer le rôle B")
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
            try:
                await db.remove_sticky(guild_id, channel_id)
            except Exception:
                # si la suppression en DB échoue, on continue (on écrasera potentiellement)
                pass

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

    @commands.command(name="decoller", aliases=["décoller", "decolle"], help="Retirer un sticky message")
    @checks.is_admin()
    async def decoller(self, ctx):
        guild_id = ctx.guild.id
        channel_id = ctx.channel.id

        # Récupérer le sticky de la DB en gérant les erreurs DB
        try:
            existing = await db.get_sticky(guild_id, channel_id)
        except Exception as e:
            print(f"[ERROR] decoller: impossible de lire le sticky en DB pour guild {guild_id} channel {channel_id}: {e}")
            await ctx.send("⚠️ Impossible de vérifier le sticky en base de données. Consulte les logs côté serveur.")
            return

        if not existing:
            await ctx.send("ℹ️ Aucun sticky défini pour ce salon.")
            return

        # existing peut être (message_id, content, author_id) ou (message_id, text, requested_by)
        message_id = None
        try:
            # essayer de normaliser en int si possible
            message_id = int(existing[0])
        except Exception:
            message_id = None

        # Supprimer le message sticky si possible (ne doit pas faire échouer la commande en cas d'erreur)
        if message_id:
            try:
                old_msg = await ctx.channel.fetch_message(message_id)
                await old_msg.delete()
            except Exception as e:
                # message introuvable ou déjà supprimé => logguer mais continuer
                print(f"[WARN] decoller: impossible de supprimer le message sticky {message_id} dans channel {channel_id}: {e}")

        # Supprimer en base (essentiel)
        try:
            await db.remove_sticky(guild_id, channel_id)
        except Exception as e:
            print(f"[ERROR] decoller: échec suppression sticky DB pour guild {guild_id} channel {channel_id}: {e}")
            await ctx.send("⚠️ Échec lors de la suppression du sticky en base. Consulte les logs côté serveur.")
            return

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
