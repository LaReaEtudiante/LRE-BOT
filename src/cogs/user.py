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
from datetime import datetime

logger = logging.getLogger('LRE-BOT.user')


class UserCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── Help ───────────────────────────────────────────────
    @commands.command(name="help", help="Afficher la liste des commandes")
    async def help_command(self, ctx: commands.Context):
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

        await ctx.send(embed=e)

    # ─── Join A ─────────────────────────────────────────────
    @commands.command(name="joina", help="Rejoindre le mode A (50-10)")
    @checks.not_in_maintenance()
    async def joina(self, ctx: commands.Context):
        added = await db.add_participant(ctx.guild.id, ctx.author.id, "A")
        if added:
            logger.info(f"✅ {ctx.author} a rejoint la session (Mode A)")
            await ctx.send(f"✅ {ctx.author.mention} a rejoint le **mode A (50-10)** !")
        else:
            logger.warning(f"⚠️ {ctx.author} a tenté de rejoindre le Mode A mais est déjà inscrit")
            await ctx.send(f"ℹ️ {ctx.author.mention}, vous êtes déjà inscrit en mode A ou B.")

    # ─── Join B ─────────────────────────────────────────────
    @commands.command(name="joinb", help="Rejoindre le mode B (25-5)")
    @checks.not_in_maintenance()
    async def joinb(self, ctx: commands.Context):
        added = await db.add_participant(ctx.guild.id, ctx.author.id, "B")
        if added:
            logger.info(f"✅ {ctx.author} a rejoint la session (Mode B)")
            await ctx.send(f"✅ {ctx.author.mention} a rejoint le **mode B (25-5)** !")
        else:
            logger.warning(f"⚠️ {ctx.author} a tenté de rejoindre le Mode B mais est déjà inscrit")
            await ctx.send(f"ℹ️ {ctx.author.mention}, vous êtes déjà inscrit en mode A ou B.")

    # ─── Leave ──────────────────────────────────────────────
    @commands.command(name="leave", help="Quitter la session en cours")
    @checks.not_in_maintenance()
    async def leave(self, ctx: commands.Context):
        join_row = await db.remove_participant(ctx.guild.id, ctx.author.id)
        if not join_row or join_row[0] is None:
            logger.warning(f"⚠️ {ctx.author} a fait *leave sans être en session")
            await ctx.send(f"🚫 {ctx.author.mention}, vous n'êtes pas inscrit.")
            return

        join_ts, mode = join_row
        end_ts = db.now_ts()
        elapsed = end_ts - join_ts
        
        # Calculer le temps de travail et de pause
        cycle = {"A": {"work": 50 * 60, "break": 10 * 60}, "B": {"work": 25 * 60, "break": 5 * 60}}
        work_duration = cycle[mode]["work"]
        break_duration = cycle[mode]["break"]
        total_cycle = work_duration + break_duration
        
        # Nombre de cycles complets
        complete_cycles = elapsed // total_cycle
        remaining_time = elapsed % total_cycle
        
        # Temps de travail effectif
        total_work = complete_cycles * work_duration
        if remaining_time <= work_duration:
            total_work += remaining_time
            total_pause = complete_cycles * break_duration
        else:
            total_work += work_duration
            total_pause = complete_cycles * break_duration + (remaining_time - work_duration)
        
        # Enregistrer le temps de travail
        await db.ajouter_temps(ctx.author.id, ctx.guild.id, total_work, mode, is_session_end=True)
        
        # Enregistrer la session détaillée
        await db.record_session(
            user_id=ctx.author.id,
            guild_id=ctx.guild.id,
            mode=mode,
            work_time=total_work,
            pause_time=total_pause,
            start_ts=join_ts,
            end_ts=end_ts
        )

        logger.info(f"✅ {ctx.author} a quitté sa session ({format_seconds(elapsed)} écoulés)")

        await ctx.send(
            f"👋 {ctx.author.mention} a quitté la session !\n"
            f"**Travail :** {format_seconds(total_work)}\n"
            f"**Pause :** {format_seconds(total_pause)}\n"
            f"**Total :** {format_seconds(elapsed)}\n"
            f"Bien joué ! 🎉"
        )

    # ─── Me ────────────────────────────────────────────────
    @commands.command(name="me", help="Afficher vos stats personnelles")
    async def me(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        user = await db.get_user_stats(ctx.author.id, guild_id)

        if not user:
            logger.warning(f"⚠️ {ctx.author} a demandé ses stats mais n'a aucune donnée")
            await ctx.send("⚠️ Vous n'avez encore aucune donnée enregistrée.")
            return

        active = await db.get_active_session(guild_id, ctx.author.id)
        if active:
            join_ts, mode = active
            elapsed = db.now_ts() - join_ts
            status = f"🟢 En **mode {mode}** depuis {format_seconds(elapsed)}"
        else:
            status = "🔴 Pas en session actuellement"

        # Calculer moyennes
        now = db.now_ts()
        first_session = user.get('first_session_date') or user.get('join_date') or now
        diff_seconds = now - first_session
        weeks_passed = max(1, diff_seconds / (7 * 24 * 3600))
        months_passed = max(1, diff_seconds / (30 * 24 * 3600))
        
        avg_week = round(user['sessions_count'] / weeks_passed, 1)
        avg_month = round(user['sessions_count'] / months_passed, 1)

        embed = discord.Embed(
            title=f"📋 Stats de {ctx.author.display_name}",
            color=discord.Color.teal()
        )
        embed.add_field(name="Statut Actuel", value=status, inline=False)
        
        embed.add_field(name="🌎 Temps Total (Travail + Repos)", value=f"{format_seconds(user['temps_total_global'])}\n*🏆 Rang: #{user['rank_total']}*", inline=False)
        
        embed.add_field(name="⏱️ Temps de Travail", value=f"{format_seconds(user['total_time'])}\n*🏆 Rang: #{user['rank_work']}*", inline=True)
        embed.add_field(name="🛌 Temps de Repos", value=f"{format_seconds(user['temps_repos'])}\n*🏆 Rang: #{user['rank_rest']}*", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True) # Empty space
        
        embed.add_field(name="🅰️ Mode A (50/10)", value=f"Travail: {format_seconds(user['total_A'])}\nRepos: {format_seconds(user['pause_time_A'])}", inline=True)
        embed.add_field(name="🅱️ Mode B (25/5)", value=f"Travail: {format_seconds(user['total_B'])}\nRepos: {format_seconds(user['pause_time_B'])}", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        
        embed.add_field(name="📚 Sessions au Total", value=str(user["sessions_count"]), inline=False)
        embed.add_field(name="📊 Moyenne Hebdo", value=f"{avg_week} sessions/semaine", inline=True)
        embed.add_field(name="📊 Moyenne Mensuelle", value=f"{avg_month} sessions/mois", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        
        embed.add_field(name="🔥 Streak Actuel", value=str(user["streak_current"]), inline=True)
        embed.add_field(name="🏆 Meilleur Streak", value=f"{user['streak_best']}\n*🏆 Rang: #{user['rank_streak']}*", inline=True)

        await ctx.send(embed=embed)

    # ─── Stats serveur ─────────────────────────────────────
    @commands.command(name="stats", help="Afficher les stats du serveur")
    async def stats(self, ctx: commands.Context):
        view = StatsView(self.bot, ctx.guild.id)
        embed = await view.generate_embed()
        embed.set_footer(text=f"Page 1/{view.max_pages + 1}")
        await ctx.send(embed=embed, view=view)

    # ─── Leaderboard ───────────────────────────────────────
    @commands.command(name="leaderboard", help="Classements divers")
    async def leaderboard(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        lb = await db.get_leaderboards(guild_id)

        embed = discord.Embed(
            title="🏆 Leaderboard",
            color=discord.Color.gold()
        )

        medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]

        for title, entries in lb.items():
            if not entries:
                value = "Aucune donnée"
            else:
                lines = []
                for i, row in enumerate(entries):
                    medal = medals[i] if i < len(medals) else f"{i+1}."
                    try:
                        uid = row[0]
                        try:
                            user = await self.bot.fetch_user(uid)
                            display = user.display_name
                        except Exception:
                            user_obj = self.bot.get_user(uid)
                            display = user_obj.display_name if user_obj else f"<{uid}>"

                        if len(row) == 2:
                            val = row[1]
                            label = format_seconds(val) if isinstance(val, int) else str(val)
                        elif len(row) == 3:
                            val1 = row[1]
                            val2 = row[2]
                            label = f"{val2} (actuel {val1})"
                        else:
                            label = " / ".join(str(x) for x in row[1:])

                        lines.append(f"{medal} **{display}** — {label}")
                    except Exception:
                        lines.append(f"{medal} <{row[0]}> — erreur de lecture")

                value = "\n".join(lines)

            embed.add_field(name=title, value=value, inline=False)

        await ctx.send(embed=embed)


class StatsView(discord.ui.View):
    def __init__(self, bot, guild_id, current_page=0):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.current_page = current_page
        self.max_pages = 10 # 0 = Global, 1 à 10 = Années
        self.current_year = datetime.now().year
        
    async def generate_embed(self):
        if self.current_page == 0:
            stats = await db.get_server_stats(self.guild_id)
            embed = discord.Embed(
                title="📊 Statistiques Globales du Serveur",
                color=discord.Color.green()
            )
            embed.add_field(
                name="👥 Utilisateurs Uniques", 
                value=f"Total: {stats['users']}\nCette Semaine: {stats['unique_users_week']}\nCe Mois: {stats['unique_users_month']}", 
                inline=False
            )
            embed.add_field(name="⏱️ Temps Total (Travail)", value=format_seconds(stats["total_time"]), inline=False)
            embed.add_field(name="📈 Moyenne par utilisateur", value=format_seconds(stats["avg_time"]), inline=False)
            
            embed.add_field(name="📚 Sessions au Total", value=str(stats["total_sessions"]), inline=False)
            embed.add_field(name="📅 Sessions Cette Semaine", value=str(stats["sessions_week"]), inline=True)
            embed.add_field(name="📆 Sessions Ce Mois", value=str(stats["sessions_month"]), inline=True)
            return embed
            
        else:
            year_offset = self.current_page - 1
            year = self.current_year - year_offset
            
            embed = discord.Embed(
                title=f"📈 Données Analytiques - Année {year}",
                description="Récapitulatif mensuel des révisions",
                color=discord.Color.blue()
            )
            
            analytics = await db.get_yearly_analytics(self.guild_id, year)
            
            months = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
            for m in range(1, 13):
                data = analytics[m]
                if data["sessions"] > 0:
                    val = f"⏱️ Travail : {format_seconds(data['work'])}\n" \
                          f"🛌 Repos : {format_seconds(data['pause'])}\n" \
                          f"👥 Uniques : {data['users']}\n" \
                          f"📚 Sessions : {data['sessions']}"
                else:
                    val = "_Aucune donnée_"
                embed.add_field(name=f"🗓️ {months[m-1]}", value=val, inline=True)
            
            return embed
            
    async def update_buttons(self, interaction: discord.Interaction):
        self.btn_prev.disabled = (self.current_page == 0)
        self.btn_next.disabled = (self.current_page == self.max_pages)
        embed = await self.generate_embed()
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.max_pages + 1}")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀️ Précédent", style=discord.ButtonStyle.secondary, disabled=True)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        await self.update_buttons(interaction)

    @discord.ui.button(label="Suivant ▶️", style=discord.ButtonStyle.primary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        await self.update_buttons(interaction)


async def setup(bot):
    await bot.add_cog(UserCommands(bot))
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
from datetime import datetime

logger = logging.getLogger('LRE-BOT.user')


class UserCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── Help ───────────────────────────────────────────────
    @commands.command(name="help", help="Afficher la liste des commandes")
    async def help_command(self, ctx: commands.Context):
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

        await ctx.send(embed=e)

    # ─── Join A ─────────────────────────────────────────────
    @commands.command(name="joina", help="Rejoindre le mode A (50-10)")
    @checks.not_in_maintenance()
    async def joina(self, ctx: commands.Context):
        added = await db.add_participant(ctx.guild.id, ctx.author.id, "A")
        if added:
            logger.info(f"✅ {ctx.author} a rejoint la session (Mode A)")
            await ctx.send(f"✅ {ctx.author.mention} a rejoint le **mode A (50-10)** !")
        else:
            logger.warning(f"⚠️ {ctx.author} a tenté de rejoindre le Mode A mais est déjà inscrit")
            await ctx.send(f"ℹ️ {ctx.author.mention}, vous êtes déjà inscrit en mode A ou B.")

    # ─── Join B ─────────────────────────────────────────────
    @commands.command(name="joinb", help="Rejoindre le mode B (25-5)")
    @checks.not_in_maintenance()
    async def joinb(self, ctx: commands.Context):
        added = await db.add_participant(ctx.guild.id, ctx.author.id, "B")
        if added:
            logger.info(f"✅ {ctx.author} a rejoint la session (Mode B)")
            await ctx.send(f"✅ {ctx.author.mention} a rejoint le **mode B (25-5)** !")
        else:
            logger.warning(f"⚠️ {ctx.author} a tenté de rejoindre le Mode B mais est déjà inscrit")
            await ctx.send(f"ℹ️ {ctx.author.mention}, vous êtes déjà inscrit en mode A ou B.")

    # ─── Leave ──────────────────────────────────────────────
    @commands.command(name="leave", help="Quitter la session en cours")
    @checks.not_in_maintenance()
    async def leave(self, ctx: commands.Context):
        join_row = await db.remove_participant(ctx.guild.id, ctx.author.id)
        if not join_row or join_row[0] is None:
            logger.warning(f"⚠️ {ctx.author} a fait *leave sans être en session")
            await ctx.send(f"🚫 {ctx.author.mention}, vous n'êtes pas inscrit.")
            return

        join_ts, mode = join_row
        end_ts = db.now_ts()
        elapsed = end_ts - join_ts
        
        # Calculer le temps de travail et de pause
        cycle = {"A": {"work": 50 * 60, "break": 10 * 60}, "B": {"work": 25 * 60, "break": 5 * 60}}
        work_duration = cycle[mode]["work"]
        break_duration = cycle[mode]["break"]
        total_cycle = work_duration + break_duration
        
        # Nombre de cycles complets
        complete_cycles = elapsed // total_cycle
        remaining_time = elapsed % total_cycle
        
        # Temps de travail effectif
        total_work = complete_cycles * work_duration
        if remaining_time <= work_duration:
            total_work += remaining_time
            total_pause = complete_cycles * break_duration
        else:
            total_work += work_duration
            total_pause = complete_cycles * break_duration + (remaining_time - work_duration)
        
        # Enregistrer le temps de travail
        await db.ajouter_temps(ctx.author.id, ctx.guild.id, total_work, mode, is_session_end=True)
        
        # Enregistrer la session détaillée
        await db.record_session(
            user_id=ctx.author.id,
            guild_id=ctx.guild.id,
            mode=mode,
            work_time=total_work,
            pause_time=total_pause,
            start_ts=join_ts,
            end_ts=end_ts
        )

        logger.info(f"✅ {ctx.author} a quitté sa session ({format_seconds(elapsed)} écoulés)")

        await ctx.send(
            f"👋 {ctx.author.mention} a quitté la session !\n"
            f"**Travail :** {format_seconds(total_work)}\n"
            f"**Pause :** {format_seconds(total_pause)}\n"
            f"**Total :** {format_seconds(elapsed)}\n"
            f"Bien joué ! 🎉"
        )

    # ─── Me ────────────────────────────────────────────────
    @commands.command(name="me", help="Afficher vos stats personnelles")
    async def me(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        user = await db.get_user_stats(ctx.author.id, guild_id)

        if not user:
            logger.warning(f"⚠️ {ctx.author} a demandé ses stats mais n'a aucune donnée")
            await ctx.send("⚠️ Vous n'avez encore aucune donnée enregistrée.")
            return

        active = await db.get_active_session(guild_id, ctx.author.id)
        if active:
            join_ts, mode = active
            elapsed = db.now_ts() - join_ts
            status = f"🟢 En **mode {mode}** depuis {format_seconds(elapsed)}"
        else:
            status = "🔴 Pas en session actuellement"

        # Calculer moyennes
        now = db.now_ts()
        first_session = user.get('first_session_date') or user.get('join_date') or now
        diff_seconds = now - first_session
        weeks_passed = max(1, diff_seconds / (7 * 24 * 3600))
        months_passed = max(1, diff_seconds / (30 * 24 * 3600))
        
        avg_week = round(user['sessions_count'] / weeks_passed, 1)
        avg_month = round(user['sessions_count'] / months_passed, 1)

        embed = discord.Embed(
            title=f"📋 Stats de {ctx.author.display_name}",
            color=discord.Color.teal()
        )
        embed.add_field(name="Statut Actuel", value=status, inline=False)
        
        embed.add_field(name="🌎 Temps Total (Travail + Repos)", value=f"{format_seconds(user['temps_total_global'])}\n*🏆 Rang: #{user['rank_total']}*", inline=False)
        
        embed.add_field(name="⏱️ Temps de Travail", value=f"{format_seconds(user['total_time'])}\n*🏆 Rang: #{user['rank_work']}*", inline=True)
        embed.add_field(name="🛌 Temps de Repos", value=f"{format_seconds(user['temps_repos'])}\n*🏆 Rang: #{user['rank_rest']}*", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True) # Empty space
        
        embed.add_field(name="🅰️ Mode A (50/10)", value=f"Travail: {format_seconds(user['total_A'])}\nRepos: {format_seconds(user['pause_time_A'])}", inline=True)
        embed.add_field(name="🅱️ Mode B (25/5)", value=f"Travail: {format_seconds(user['total_B'])}\nRepos: {format_seconds(user['pause_time_B'])}", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        
        embed.add_field(name="📚 Sessions au Total", value=str(user["sessions_count"]), inline=False)
        embed.add_field(name="📊 Moyenne Hebdo", value=f"{avg_week} sessions/semaine", inline=True)
        embed.add_field(name="📊 Moyenne Mensuelle", value=f"{avg_month} sessions/mois", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        
        embed.add_field(name="🔥 Streak Actuel", value=str(user["streak_current"]), inline=True)
        embed.add_field(name="🏆 Meilleur Streak", value=f"{user['streak_best']}\n*🏆 Rang: #{user['rank_streak']}*", inline=True)

        await ctx.send(embed=embed)

    # ─── Stats serveur ─────────────────────────────────────
    @commands.command(name="stats", help="Afficher les stats du serveur")
    async def stats(self, ctx: commands.Context):
        view = StatsView(self.bot, ctx.guild.id)
        embed = await view.generate_embed()
        embed.set_footer(text=f"Page 1/{view.max_pages + 1}")
        await ctx.send(embed=embed, view=view)

    # ─── Leaderboard ───────────────────────────────────────
    @commands.command(name="leaderboard", help="Classements divers")
    async def leaderboard(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        lb = await db.get_leaderboards(guild_id)

        embed = discord.Embed(
            title="🏆 Leaderboard",
            color=discord.Color.gold()
        )

        medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]

        for title, entries in lb.items():
            if not entries:
                value = "Aucune donnée"
            else:
                lines = []
                for i, row in enumerate(entries):
                    medal = medals[i] if i < len(medals) else f"{i+1}."
                    try:
                        uid = row[0]
                        try:
                            user = await self.bot.fetch_user(uid)
                            display = user.display_name
                        except Exception:
                            user_obj = self.bot.get_user(uid)
                            display = user_obj.display_name if user_obj else f"<{uid}>"

                        if len(row) == 2:
                            val = row[1]
                            label = format_seconds(val) if isinstance(val, int) else str(val)
                        elif len(row) == 3:
                            val1 = row[1]
                            val2 = row[2]
                            label = f"{val2} (actuel {val1})"
                        else:
                            label = " / ".join(str(x) for x in row[1:])

                        lines.append(f"{medal} **{display}** — {label}")
                    except Exception:
                        lines.append(f"{medal} <{row[0]}> — erreur de lecture")

                value = "\n".join(lines)

            embed.add_field(name=title, value=value, inline=False)

        await ctx.send(embed=embed)


class StatsView(discord.ui.View):
    def __init__(self, bot, guild_id, current_page=0):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.current_page = current_page
        self.max_pages = 10 # 0 = Global, 1 à 10 = Années
        self.current_year = datetime.now().year
        
    async def generate_embed(self):
        if self.current_page == 0:
            stats = await db.get_server_stats(self.guild_id)
            embed = discord.Embed(
                title="📊 Statistiques Globales du Serveur",
                color=discord.Color.green()
            )
            embed.add_field(
                name="👥 Utilisateurs Uniques", 
                value=f"Total: {stats['users']}\nCette Semaine: {stats['unique_users_week']}\nCe Mois: {stats['unique_users_month']}", 
                inline=False
            )
            embed.add_field(name="⏱️ Temps Total (Travail)", value=format_seconds(stats["total_time"]), inline=False)
            embed.add_field(name="📈 Moyenne par utilisateur", value=format_seconds(stats["avg_time"]), inline=False)
            
            embed.add_field(name="📚 Sessions au Total", value=str(stats["total_sessions"]), inline=False)
            embed.add_field(name="📅 Sessions Cette Semaine", value=str(stats["sessions_week"]), inline=True)
            embed.add_field(name="📆 Sessions Ce Mois", value=str(stats["sessions_month"]), inline=True)
            return embed
            
        else:
            year_offset = self.current_page - 1
            year = self.current_year - year_offset
            
            embed = discord.Embed(
                title=f"📈 Données Analytiques - Année {year}",
                description="Récapitulatif mensuel des révisions",
                color=discord.Color.blue()
            )
            
            analytics = await db.get_yearly_analytics(self.guild_id, year)
            
            months = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
            for m in range(1, 13):
                data = analytics[m]
                if data["sessions"] > 0:
                    val = f"⏱️ Travail : {format_seconds(data['work'])}\n" \
                          f"🛌 Repos : {format_seconds(data['pause'])}\n" \
                          f"👥 Uniques : {data['users']}\n" \
                          f"📚 Sessions : {data['sessions']}"
                else:
                    val = "_Aucune donnée_"
                embed.add_field(name=f"🗓️ {months[m-1]}", value=val, inline=True)
            
            return embed
            
    async def update_buttons(self, interaction: discord.Interaction):
        self.btn_prev.disabled = (self.current_page == 0)
        self.btn_next.disabled = (self.current_page == self.max_pages)
        embed = await self.generate_embed()
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.max_pages + 1}")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀️ Précédent", style=discord.ButtonStyle.secondary, disabled=True)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        await self.update_buttons(interaction)

    @discord.ui.button(label="Suivant ▶️", style=discord.ButtonStyle.primary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        await self.update_buttons(interaction)


async def setup(bot):
    await bot.add_cog(UserCommands(bot))
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

        await ctx.send(embed=e)

    # ─── Join A ─────────────────────────────────────────────
    @commands.command(name="joina", help="Rejoindre le mode A (50-10)")
    @checks.not_in_maintenance()
    async def joina(self, ctx: commands.Context):
        added = await db.add_participant(ctx.guild.id, ctx.author.id, "A")
        if added:
            logger.info(f"✅ {ctx.author} a rejoint la session (Mode A)")
            await ctx.send(f"✅ {ctx.author.mention} a rejoint le **mode A (50-10)** !")
        else:
            logger.warning(f"⚠️ {ctx.author} a tenté de rejoindre le Mode A mais est déjà inscrit")
            await ctx.send(f"ℹ️ {ctx.author.mention}, vous êtes déjà inscrit en mode A ou B.")

    # ─── Join B ─────────────────────────────────────────────
    @commands.command(name="joinb", help="Rejoindre le mode B (25-5)")
    @checks.not_in_maintenance()
    async def joinb(self, ctx: commands.Context):
        added = await db.add_participant(ctx.guild.id, ctx.author.id, "B")
        if added:
            logger.info(f"✅ {ctx.author} a rejoint la session (Mode B)")
            await ctx.send(f"✅ {ctx.author.mention} a rejoint le **mode B (25-5)** !")
        else:
            logger.warning(f"⚠️ {ctx.author} a tenté de rejoindre le Mode B mais est déjà inscrit")
            await ctx.send(f"ℹ️ {ctx.author.mention}, vous êtes déjà inscrit en mode A ou B.")

    # ─── Leave ──────────────────────────────────────────────
    @commands.command(name="leave", help="Quitter la session en cours")
    @checks.not_in_maintenance()
    async def leave(self, ctx: commands.Context):
        join_row = await db.remove_participant(ctx.guild.id, ctx.author.id)
        if not join_row or join_row[0] is None:
            logger.warning(f"⚠️ {ctx.author} a fait *leave sans être en session")
            await ctx.send(f"🚫 {ctx.author.mention}, vous n'êtes pas inscrit.")
            return

        join_ts, mode = join_row
        end_ts = db.now_ts()
        elapsed = end_ts - join_ts
        
        # Calculer le temps de travail et de pause
        cycle = {"A": {"work": 50 * 60, "break": 10 * 60}, "B": {"work": 25 * 60, "break": 5 * 60}}
        work_duration = cycle[mode]["work"]
        break_duration = cycle[mode]["break"]
        total_cycle = work_duration + break_duration
        
        # Nombre de cycles complets
        complete_cycles = elapsed // total_cycle
        remaining_time = elapsed % total_cycle
        
        # Temps de travail effectif
        total_work = complete_cycles * work_duration
        if remaining_time <= work_duration:
            total_work += remaining_time
            total_pause = complete_cycles * break_duration
        else:
            total_work += work_duration
            total_pause = complete_cycles * break_duration + (remaining_time - work_duration)
        
        # Enregistrer le temps de travail
        await db.ajouter_temps(ctx.author.id, ctx.guild.id, total_work, mode, is_session_end=True)
        
        # Enregistrer la session détaillée
        await db.record_session(
            user_id=ctx.author.id,
            guild_id=ctx.guild.id,
            mode=mode,
            work_time=total_work,
            pause_time=total_pause,
            start_ts=join_ts,
            end_ts=end_ts
        )

        logger.info(f"✅ {ctx.author} a quitté sa session ({format_seconds(elapsed)} écoulés)")

        await ctx.send(
            f"👋 {ctx.author.mention} a quitté la session !\n"
            f"**Travail :** {format_seconds(total_work)}\n"
            f"**Pause :** {format_seconds(total_pause)}\n"
            f"**Total :** {format_seconds(elapsed)}\n"
            f"Bien joué ! 🎉"
        )

    # ─── Me ────────────────────────────────────────────────
    @commands.command(name="me", help="Afficher vos stats personnelles")
    async def me(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        user = await db.get_user(ctx.author.id, guild_id)

        if not user:
            logger.warning(f"⚠️ {ctx.author} a demandé ses stats mais n'a aucune donnée")
            await ctx.send("⚠️ Vous n'avez encore aucune donnée enregistrée.")
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
