# ==========================
# LRE-BOT/src/cogs/user.py
# ==========================
import discord
from discord.ext import commands
from core import db, config
from utils.time_format import format_seconds
from utils import checks
import logging
import time

logger = logging.getLogger('LRE-BOT.user')


class UserCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── Help ───────────────────────────────────────────────
    @commands.command(name="help", help="Afficher la liste des commandes")
    async def help_command(self, ctx: commands.Context):
        timestamp = time.time()
        logger.info(f"⚡ HELP COMMAND EXÉCUTÉE - timestamp={timestamp} - author={ctx.author} - message_id={ctx.message.id}")
        
        prefix = ctx.prefix

        e = discord.Embed(
            title="📖 Aide - Commandes disponibles",
            color=discord.Color.blue()
        )

        e.add_field(
            name="👤 Étudiants",
            value=(
                f"{prefix}joina — rejoindre le mode A (50/10)\n"
                f"{prefix}joinb — rejoindre le mode B (25/5)\n"
                f"{prefix}leave — quitter la session en cours\n"
                f"{prefix}me — voir vos stats détaillées\n"
                f"{prefix}stats — statistiques du serveur\n"
                f"{prefix}leaderboard — classements divers\n"
            ),
            inline=False
        )

        e.add_field(
            name="🛠️ Administrateurs",
            value=(
                f"{prefix}maintenance — dés/activer le mode maintenance\n"
                f"{prefix}status — voir l'état global du bot\n"
                f"{prefix}colle — coller un sticky message\n"
                f"{prefix}decoller — retirer un sticky message\n"
                f"{prefix}clear_stats — réinitialiser toutes les stats\n"
            ),
            inline=False
        )

        logger.info(f"⚡ HELP COMMAND - Envoi de l'embed - timestamp={timestamp}")
        await ctx.send(embed=e)
        logger.info(f"⚡ HELP COMMAND - Embed envoyé ✅ - timestamp={timestamp}")

    # ─── Join A ─────────────────────────────────────────────
    @commands.command(name="joina", help="Rejoindre le mode A (50-10)")
    @checks.not_in_maintenance()
    async def joina(self, ctx: commands.Context):
        added = await db.add_participant(ctx.guild.id, ctx.author.id, "A")
        if added:
            await ctx.send(f"✅ {ctx.author.mention} a rejoint le **mode A (50-10)** !")
        else:
            await ctx.send(f"ℹ️ {ctx.author.mention}, vous êtes déjà inscrit en mode A ou B.")

    # ─── Join B ─────────────────────────────────────────────
    @commands.command(name="joinb", help="Rejoindre le mode B (25-5)")
    @checks.not_in_maintenance()
    async def joinb(self, ctx: commands.Context):
        added = await db.add_participant(ctx.guild.id, ctx.author.id, "B")
        if added:
            await ctx.send(f"✅ {ctx.author.mention} a rejoint le **mode B (25-5)** !")
        else:
            await ctx.send(f"ℹ️ {ctx.author.mention}, vous êtes déjà inscrit en mode A ou B.")

    # ─── Leave ──────────────────────────────────────────────
    @commands.command(name="leave", help="Quitter la session en cours")
    @checks.not_in_maintenance()
    async def leave(self, ctx: commands.Context):
        join_row = await db.remove_participant(ctx.guild.id, ctx.author.id)
        if not join_row or join_row[0] is None:
            await ctx.send(f"🚫 {ctx.author.mention}, vous n'êtes pas inscrit.")
            return

        join_ts, mode = join_row
        elapsed = db.now_ts() - join_ts
        await db.ajouter_temps(ctx.author.id, ctx.guild.id, elapsed, mode, is_session_end=True)

        await ctx.send(f"👋 {ctx.author.mention} a quitté. +{format_seconds(elapsed)} ajoutées.")

    # ─── Me ────────────────────────────────────────────────
    @commands.command(name="me", help="Afficher vos stats personnelles")
    async def me(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        user = await db.get_user(ctx.author.id, guild_id)

        if not user:
            await ctx.send("⚠️ Vous n'avez encore aucune donnée enregistrée.")
            return

        # Session en cours ?
        active = await db.get_active_session(guild_id, ctx.author.id) if hasattr(db, "get_active_session") else None
        if active:
            join_ts, mode = active
            elapsed = db.now_ts() - join_ts
            status = f"En **mode {mode}** depuis {format_seconds(elapsed)}"
        else:
            status = "Pas en session actuellement"

        embed = discord.Embed(
            title=f"📋 Stats de {ctx.author.display_name}",
            color=discord.Color.teal()
        )
        embed.add_field(name="Session en cours", value=status, inline=False)
        embed.add_field(name="⏱ Temps total", value=format_seconds(user["total_time"]), inline=False)
        embed.add_field(name="🅰️ Mode A travail", value=format_seconds(user["total_A"]), inline=True)
        embed.add_field(name="🅱️ Mode B travail", value=format_seconds(user["total_B"]), inline=True)
        embed.add_field(name="📚 Sessions", value=user["sessions_count"], inline=True)
        embed.add_field(name="🔥 Streak actuel", value=user["streak_current"], inline=True)
        embed.add_field(name="🏆 Meilleur streak", value=user["streak_best"], inline=True)

        await ctx.send(embed=embed)

    # ─── Stats serveur ─────────────────────────────────────
    @commands.command(name="stats", help="Afficher les stats du serveur")
    async def stats(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        stats = await db.get_server_stats(guild_id)

        embed = discord.Embed(
            title="📊 Statistiques du serveur",
            color=discord.Color.green()
        )
        embed.add_field(name="Utilisateurs uniques", value=str(stats["users"]), inline=False)
        embed.add_field(name="Temps total", value=format_seconds(stats["total_time"]), inline=False)
        embed.add_field(name="Moyenne/utilisateur", value=format_seconds(stats["avg_time"]), inline=False)
        embed.add_field(name="📅 Sessions 7 jours", value=stats.get("last_7_days", "N/A"), inline=False)
        embed.add_field(name="🗓 Sessions 4 semaines", value=stats.get("last_4_weeks", "N/A"), inline=False)

        await ctx.send(embed=embed)

    # ─── Leaderboard ───────────────────────────────────────
    @commands.command(name="leaderboard", help="Classements divers")
    async def leaderboard(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        lb = await db.get_leaderboards(guild_id)

        embed = discord.Embed(
            title="🏆 Leaderboard",
            color=discord.Color.gold()
        )

        for title, entries in lb.items():
            if not entries:
                value = "aucune donnée"
            else:
                lines = []
                for i, row in enumerate(entries, start=1):
                    try:
                        uid = row[0]
                        # Récupérer display_name de façon sûre
                        try:
                            user = await self.bot.fetch_user(uid)
                            display = user.display_name
                        except Exception:
                            user_obj = self.bot.get_user(uid)
                            display = user_obj.display_name if user_obj else f"<{uid}>"

                        # Construire le label selon le nombre de colonnes
                        if len(row) == 2:
                            val = row[1]
                            label = format_seconds(val) if isinstance(val, int) else str(val)
                        elif len(row) == 3:
                            # ex: (user_id, streak_current, streak_best)
                            val1 = row[1]
                            val2 = row[2]
                            label = f"{val2} (actuel {val1})"
                        else:
                            label = " / ".join(str(x) for x in row[1:])

                        lines.append(f"{i}. {display} — {label}")
                    except Exception:
                        lines.append(f"{i}. <{row[0]}> — erreur de lecture")

                value = "\n".join(lines)

            embed.add_field(name=title, value=value, inline=False)

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(UserCommands(bot))
