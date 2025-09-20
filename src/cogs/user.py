# ==========================
# LRE-BOT/src/cogs/user.py
# ==========================
import discord
from discord.ext import commands
from core import db, config
from utils.time_format import format_seconds
from utils import checks

class UserCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

# ─── Help ───────────────────────────────────────────────
    @commands.command(name="help", help="Afficher la liste des commandes")
    async def help_command(self, ctx: commands.Context):
        prefix = ctx.prefix
        # Vérifications de config
        role_a = await db.get_setting("pomodoro_role_A", default=None)
        role_b = await db.get_setting("pomodoro_role_B", default=None)
        channel_id = await db.get_setting("channel_id", default=None)

        if not role_a or not role_b or not channel_id:
            if ctx.author.guild_permissions.administrator:
                await ctx.send(
                    "⚠️ Le bot n’est pas encore configuré correctement.\n"
                    "➡️ Tapez `*status` pour voir les étapes de configuration."
                )
            else:
                await ctx.send(
                    "⚠️ Le bot n’est pas encore configuré correctement.\n"
                    "➡️ Merci de contacter un administrateur."
                )
            return

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
                f"{prefix}status — voir l’état global du bot\n"
            ),
            inline=False
        )

        e.add_field(
            name="🛠️ Administrateurs",
            value=(
                f"{prefix}maintenance — dés/activer le mode maintenance\n"
                f"{prefix}defs — définir le salon Pomodoro\n"
                f"{prefix}defa — définir ou créer le rôle A\n"
                f"{prefix}defb — définir ou créer le rôle B\n"
                f"{prefix}colle — coller un sticky message\n"
                f"{prefix}decoller — retirer un sticky message\n"
                f"{prefix}clear_stats — réinitialiser toutes les stats\n"
                f"{prefix}update — mise à jour & redémarrage du bot\n"
            ),
            inline=False
        )

        await ctx.send(embed=e)    

    # ─── Join A ─────────────────────────────────────────────
    @commands.command(name="joina", help="Rejoindre le mode A (50-10)")
    @checks.in_pomodoro_channel()
    @checks.roles_are_set()
    @checks.not_in_maintenance()
    async def joina(self, ctx: commands.Context):
        await db.add_participant(ctx.guild.id, ctx.author.id, "A")
        await ctx.send(f"✅ {ctx.author.mention} a rejoint le **mode A (50-10)** !")

    # ─── Join B ─────────────────────────────────────────────
    @commands.command(name="joinb", help="Rejoindre le mode B (25-5)")
    @checks.in_pomodoro_channel()
    @checks.roles_are_set()
    @checks.not_in_maintenance()
    async def joinb(self, ctx: commands.Context):
        await db.add_participant(ctx.guild.id, ctx.author.id, "B")
        await ctx.send(f"✅ {ctx.author.mention} a rejoint le **mode B (25-5)** !")

    # ─── Leave ──────────────────────────────────────────────
    @commands.command(name="leave", help="Quitter la session en cours")
    @checks.in_pomodoro_channel()
    @checks.roles_are_set()
    @checks.not_in_maintenance()
    async def leave(self, ctx: commands.Context):
        join_ts, mode = await db.remove_participant(ctx.guild.id, ctx.author.id)
        if join_ts is None:
            await ctx.send(f"🚫 {ctx.author.mention}, vous n’êtes pas inscrit.")
            return

        elapsed = db.now_ts() - join_ts
        await db.ajouter_temps(ctx.author.id, ctx.guild.id, elapsed, mode, is_session_end=True)

        await ctx.send(f"👋 {ctx.author.mention} a quitté. +{format_seconds(elapsed)} ajoutées.")

    # ─── Me ────────────────────────────────────────────────
    @commands.command(name="me", help="Afficher vos stats personnelles")
    @checks.in_pomodoro_channel()
    @checks.roles_are_set()
    @checks.not_in_maintenance()
    async def me(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        user = await db.get_user(ctx.author.id, guild_id)

        if not user:
            await ctx.send("⚠️ Vous n’avez encore aucune donnée enregistrée.")
            return

        # Session en cours ?
        active = await db.get_active_session(guild_id, ctx.author.id)
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
    @checks.in_pomodoro_channel()
    @checks.roles_are_set()
    @checks.not_in_maintenance()
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
        embed.add_field(name="📅 Sessions 7 jours", value=stats["last_7_days"], inline=False)
        embed.add_field(name="🗓 Sessions 4 semaines", value=stats["last_4_weeks"], inline=False)

        await ctx.send(embed=embed)

    # ─── Leaderboard ───────────────────────────────────────
    @commands.command(name="leaderboard", help="Classements divers")
    @checks.in_pomodoro_channel()
    @checks.roles_are_set()
    @checks.not_in_maintenance()
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
                for i, (uid, val) in enumerate(entries, start=1):
                    user = await self.bot.fetch_user(uid)
                    if isinstance(val, int):
                        label = format_seconds(val)
                    else:
                        label = str(val)
                    lines.append(f"{i}. {user.display_name} — {label}")
                value = "\n".join(lines)

            embed.add_field(name=title, value=value, inline=False)

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(UserCommands(bot))
