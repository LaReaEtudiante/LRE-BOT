# ==========================
# LRE-BOT/src/cogs/pomodoro.py
# ==========================
import discord
from discord.ext import commands, tasks
from core import db
from utils.time_format import format_seconds
import logging

logger = logging.getLogger('LRE-BOT.pomodoro')

# Configuration des cycles Pomodoro
POMODORO_MODES = {
    "A": {"work": 50 * 60, "break": 10 * 60},  # 50 min travail, 10 min pause
    "B": {"work": 25 * 60, "break": 5 * 60}     # 25 min travail, 5 min pause
}


class PresenceView(discord.ui.View):
    def __init__(self, bot, guild_id, user_id, mode, join_ts, cycles_completed):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.mode = mode
        self.join_ts = join_ts
        self.cycles_completed = cycles_completed

    @discord.ui.button(label="✅ Continuer", style=discord.ButtonStyle.success)
    async def btn_continue(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Mettre à jour l'état (validé = 0)
        await db.update_participant_state(self.guild_id, self.user_id, validated=0)
        
        cycle = POMODORO_MODES.get(self.mode)
        work_duration = cycle["work"]
        break_duration = cycle["break"]
        
        session_work = (self.cycles_completed + 1) * work_duration
        session_break = self.cycles_completed * break_duration
        
        for child in self.children:
            child.disabled = True
            
        await interaction.response.edit_message(
            content=f"✅ Présence confirmée ! Tu en es à **{format_seconds(session_work)}** de travail et **{format_seconds(session_break)}** de repos pour cette session.",
            view=self
        )
        logger.info(f"✅ {interaction.user} a confirmé sa présence (Mode {self.mode})")

        # Vérifier si on doit enregistrer le cycle MAINTENANT (s'il a cliqué pendant le délai de grâce)
        now = db.now_ts()
        elapsed = now - self.join_ts
        total_cycle = work_duration + break_duration
        
        if elapsed // total_cycle > self.cycles_completed:
            # On est déjà dans le cycle suivant, donc l'enregistrement de fin de cycle a été sauté. On le fait ici.
            await db.ajouter_temps(
                user_id=self.user_id,
                guild_id=self.guild_id,
                temps_sec=work_duration,
                mode=self.mode,
                is_session_end=False
            )
            session_start = self.join_ts + self.cycles_completed * total_cycle
            session_end = session_start + total_cycle
            await db.record_session(
                user_id=self.user_id,
                guild_id=self.guild_id,
                mode=self.mode,
                work_time=work_duration,
                pause_time=break_duration,
                start_ts=session_start,
                end_ts=session_end
            )
            await db.update_participant_state(self.guild_id, self.user_id, increment_cycles=True)
            
            nb_cycles = self.cycles_completed + 1
            await interaction.followup.send(
                f"🔄 **Nouveau cycle !**\n"
                f"C'est parti pour une nouvelle session de {format_seconds(work_duration)} !\n"
                f"Cycle n°{nb_cycles + 1} 💪"
            )

    @discord.ui.button(label="❌ Quitter", style=discord.ButtonStyle.danger)
    async def btn_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        cycle = POMODORO_MODES.get(self.mode)
        work_duration = cycle["work"]
        break_duration = cycle["break"]
        
        # Enregistrer le temps du cycle actuel (travail complété)
        await db.ajouter_temps(
            user_id=self.user_id,
            guild_id=self.guild_id,
            temps_sec=work_duration,
            mode=self.mode,
            is_session_end=True
        )
        session_start = self.join_ts + self.cycles_completed * (work_duration + break_duration)
        session_end = db.now_ts()
        
        await db.record_session(
            user_id=self.user_id,
            guild_id=self.guild_id,
            mode=self.mode,
            work_time=work_duration,
            pause_time=0,
            start_ts=session_start,
            end_ts=session_end
        )
        
        await db.remove_participant(self.guild_id, self.user_id)
        
        session_work = (self.cycles_completed + 1) * work_duration
        session_break = self.cycles_completed * break_duration
        
        for child in self.children:
            child.disabled = True
            
        await interaction.response.edit_message(
            content=f"❌ Tu as quitté la session.\nBilan de ta session : **{format_seconds(session_work)}** de travail et **{format_seconds(session_break)}** de repos. À bientôt ! 👋",
            view=self
        )
        logger.info(f"✅ {interaction.user} a choisi de quitter la session depuis les boutons (Mode {self.mode})")


class Pomodoro(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pomodoro_task.start()
        logger.info("✅ Pomodoro Cog initialisé et tâche démarrée")

    def cog_unload(self):
        self.pomodoro_task.cancel()

    @tasks.loop(minutes=1)
    async def pomodoro_task(self):
        """Tâche de fond qui gère les cycles Pomodoro"""
        # Récupérer tous les participants actifs
        async with db.aiosqlite.connect(db.DB_PATH) as conn:
            async with conn.execute("""
                SELECT guild_id, user_id, join_ts, mode, validated, cycles_completed 
                FROM participants
            """) as cursor:
                participants = await cursor.fetchall()

        now = db.now_ts()

        for guild_id, user_id, join_ts, mode, validated, cycles_completed in participants:
            elapsed = now - join_ts
            cycle = POMODORO_MODES.get(mode)
            
            if not cycle:
                continue

            work_duration = cycle["work"]
            break_duration = cycle["break"]
            total_cycle = work_duration + break_duration

            position_in_cycle = elapsed % total_cycle
            current_cycle_index = elapsed // total_cycle

            guild = self.bot.get_guild(guild_id)
            member = guild.get_member(user_id) if guild else None

            # Événement 1 : Début de la pause -> Envoi du message + boutons
            if position_in_cycle >= work_duration and validated == 0 and current_cycle_index == cycles_completed:
                await db.update_participant_state(guild_id, user_id, validated=1)
                
                if member:
                    try:
                        view = PresenceView(self.bot, guild_id, user_id, mode, join_ts, cycles_completed)
                        await member.send(
                            f"⏸️ **Pause bien méritée !**\n"
                            f"Tu as terminé une session de {format_seconds(work_duration)} !\n"
                            f"Prends {format_seconds(break_duration)} de repos. 🌟\n\n"
                            f"⚠️ **Merci de confirmer ta présence pour continuer !**",
                            view=view
                        )
                        logger.info(f"⏳ Boutons de présence envoyés à {member} (mode {mode})")
                    except discord.Forbidden:
                        logger.warning(f"⚠️ Impossible d'envoyer un DM à {member}")
                continue

            # Événement 2 : Rappel 1 minute avant la reprise
            if position_in_cycle >= (total_cycle - 60) and validated == 1 and current_cycle_index == cycles_completed:
                await db.update_participant_state(guild_id, user_id, validated=2)
                if member:
                    try:
                        await member.send(f"⏳ <@{user_id}> Plus qu'une minute avant la reprise ! N'oublie pas de valider ta présence en cliquant sur ✅ Continuer !")
                        logger.info(f"⏳ Rappel 1min envoyé à {member} (mode {mode})")
                    except:
                        pass
                continue

            # Événement 3 : Fin du cycle -> Enregistrement normal (si validé)
            if current_cycle_index > cycles_completed and validated == 0:
                try:
                    await db.ajouter_temps(
                        user_id=user_id,
                        guild_id=guild_id,
                        temps_sec=work_duration,
                        mode=mode,
                        is_session_end=False
                    )
                    session_start = join_ts + cycles_completed * total_cycle
                    session_end = session_start + total_cycle
                    await db.record_session(
                        user_id=user_id,
                        guild_id=guild_id,
                        mode=mode,
                        work_time=work_duration,
                        pause_time=break_duration,
                        start_ts=session_start,
                        end_ts=session_end
                    )
                    await db.update_participant_state(guild_id, user_id, increment_cycles=True)
                    
                    if member:
                        try:
                            await member.send(
                                f"🔄 **Nouveau cycle !**\n"
                                f"C'est parti pour une nouvelle session de {format_seconds(work_duration)} !\n"
                                f"Cycle n°{cycles_completed + 2} 💪"
                            )
                            logger.info(f"✅ Nouveau cycle démarré pour {member} (Cycle {cycles_completed + 2})")
                        except:
                            pass
                except Exception as e:
                    logger.error(f"❌ Erreur lors de l'enregistrement du cycle: {e}")
                continue

            # Événement 4 : Délai de grâce expiré (Expulsion)
            grace_period = 10 * 60 if mode == "A" else 5 * 60
            if current_cycle_index > cycles_completed and position_in_cycle >= grace_period and validated > 0:
                # Calcul de la pénalité
                session_verified_time = cycles_completed * work_duration
                bonus_time = 0
                if session_verified_time < 3600:
                    bonus_time = 25 * 60
                elif session_verified_time < 7200:
                    bonus_time = 15 * 60
                
                if bonus_time > 0:
                    await db.ajouter_temps(user_id, guild_id, bonus_time, mode, is_session_end=True)
                    await db.record_session(
                        user_id=user_id,
                        guild_id=guild_id,
                        mode=mode,
                        work_time=bonus_time,
                        pause_time=0,
                        start_ts=now - bonus_time,
                        end_ts=now
                    )
                
                await db.remove_participant(guild_id, user_id)
                logger.info(f"❌ {member} expulsé de la session pour inactivité (bonus: {bonus_time}s).")
                
                if member:
                    try:
                        msg = f"❌ **Session annulée pour inactivité.** Tu n'as pas validé ta présence après le délai de grâce.\n"
                        if bonus_time > 0:
                            msg += f"🎁 Je t'ai tout de même accordé **{format_seconds(bonus_time)}** de révision en guise de consolation pour ce dernier cycle !"
                        else:
                            msg += "Aucun temps supplémentaire n'a été ajouté car tu as déjà plus de 2h de révision validée."
                        await member.send(msg)
                    except:
                        pass

    @pomodoro_task.before_loop
    async def before_pomodoro_task(self):
        """Attendre que le bot soit prêt avant de démarrer la tâche"""
        await self.bot.wait_until_ready()
        logger.info("✅ Pomodoro task prête à démarrer")

async def setup(bot):
    await bot.add_cog(Pomodoro(bot))
# ==========================
# LRE-BOT/src/cogs/pomodoro.py
# ==========================
import discord
from discord.ext import commands, tasks
from core import db
from utils.time_format import format_seconds
import logging

logger = logging.getLogger('LRE-BOT.pomodoro')

# Configuration des cycles Pomodoro
POMODORO_MODES = {
    "A": {"work": 50 * 60, "break": 10 * 60},  # 50 min travail, 10 min pause
    "B": {"work": 25 * 60, "break": 5 * 60}     # 25 min travail, 5 min pause
}


class PresenceView(discord.ui.View):
    def __init__(self, bot, guild_id, user_id, mode, join_ts, cycles_completed):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.mode = mode
        self.join_ts = join_ts
        self.cycles_completed = cycles_completed

    @discord.ui.button(label="✅ Continuer", style=discord.ButtonStyle.success)
    async def btn_continue(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Mettre à jour l'état (validé = 0)
        await db.update_participant_state(self.guild_id, self.user_id, validated=0)
        
        cycle = POMODORO_MODES.get(self.mode)
        work_duration = cycle["work"]
        break_duration = cycle["break"]
        
        session_work = (self.cycles_completed + 1) * work_duration
        session_break = self.cycles_completed * break_duration
        
        for child in self.children:
            child.disabled = True
            
        await interaction.response.edit_message(
            content=f"✅ Présence confirmée ! Tu en es à **{format_seconds(session_work)}** de travail et **{format_seconds(session_break)}** de repos pour cette session.",
            view=self
        )

        # Vérifier si on doit enregistrer le cycle MAINTENANT (s'il a cliqué pendant le délai de grâce)
        now = db.now_ts()
        elapsed = now - self.join_ts
        total_cycle = work_duration + break_duration
        
        if elapsed // total_cycle > self.cycles_completed:
            # On est déjà dans le cycle suivant, donc l'enregistrement de fin de cycle a été sauté. On le fait ici.
            await db.ajouter_temps(
                user_id=self.user_id,
                guild_id=self.guild_id,
                temps_sec=work_duration,
                mode=self.mode,
                is_session_end=False
            )
            session_start = self.join_ts + self.cycles_completed * total_cycle
            session_end = session_start + total_cycle
            await db.record_session(
                user_id=self.user_id,
                guild_id=self.guild_id,
                mode=self.mode,
                work_time=work_duration,
                pause_time=break_duration,
                start_ts=session_start,
                end_ts=session_end
            )
            await db.update_participant_state(self.guild_id, self.user_id, increment_cycles=True)
            
            nb_cycles = self.cycles_completed + 1
            await interaction.followup.send(
                f"🔄 **Nouveau cycle !**\n"
                f"C'est parti pour une nouvelle session de {format_seconds(work_duration)} !\n"
                f"Cycle n°{nb_cycles + 1} 💪"
            )

    @discord.ui.button(label="❌ Quitter", style=discord.ButtonStyle.danger)
    async def btn_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        cycle = POMODORO_MODES.get(self.mode)
        work_duration = cycle["work"]
        break_duration = cycle["break"]
        
        # Enregistrer le temps du cycle actuel (travail complété)
        await db.ajouter_temps(
            user_id=self.user_id,
            guild_id=self.guild_id,
            temps_sec=work_duration,
            mode=self.mode,
            is_session_end=True
        )
        session_start = self.join_ts + self.cycles_completed * (work_duration + break_duration)
        session_end = db.now_ts()
        
        await db.record_session(
            user_id=self.user_id,
            guild_id=self.guild_id,
            mode=self.mode,
            work_time=work_duration,
            pause_time=0,
            start_ts=session_start,
            end_ts=session_end
        )
        
        await db.remove_participant(self.guild_id, self.user_id)
        
        session_work = (self.cycles_completed + 1) * work_duration
        session_break = self.cycles_completed * break_duration
        
        for child in self.children:
            child.disabled = True
            
        await interaction.response.edit_message(
            content=f"❌ Tu as quitté la session.\nBilan de ta session : **{format_seconds(session_work)}** de travail et **{format_seconds(session_break)}** de repos. À bientôt ! 👋",
            view=self
        )


class Pomodoro(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pomodoro_task.start()
        logger.info("🍅 Pomodoro Cog initialisé")

    def cog_unload(self):
        self.pomodoro_task.cancel()

    @tasks.loop(minutes=1)
    async def pomodoro_task(self):
        """Tâche de fond qui gère les cycles Pomodoro"""
        # Récupérer tous les participants actifs
        async with db.aiosqlite.connect(db.DB_PATH) as conn:
            async with conn.execute("""
                SELECT guild_id, user_id, join_ts, mode, validated, cycles_completed 
                FROM participants
            """) as cursor:
                participants = await cursor.fetchall()

        now = db.now_ts()

        for guild_id, user_id, join_ts, mode, validated, cycles_completed in participants:
            elapsed = now - join_ts
            cycle = POMODORO_MODES.get(mode)
            
            if not cycle:
                continue

            work_duration = cycle["work"]
            break_duration = cycle["break"]
            total_cycle = work_duration + break_duration

            position_in_cycle = elapsed % total_cycle
            current_cycle_index = elapsed // total_cycle

            guild = self.bot.get_guild(guild_id)
            member = guild.get_member(user_id) if guild else None

            # Événement 1 : Début de la pause -> Envoi du message + boutons
            if position_in_cycle >= work_duration and validated == 0 and current_cycle_index == cycles_completed:
                await db.update_participant_state(guild_id, user_id, validated=1)
                
                if member:
                    try:
                        view = PresenceView(self.bot, guild_id, user_id, mode, join_ts, cycles_completed)
                        await member.send(
                            f"⏸️ **Pause bien méritée !**\n"
                            f"Tu as terminé une session de {format_seconds(work_duration)} !\n"
                            f"Prends {format_seconds(break_duration)} de repos. 🌟\n\n"
                            f"⚠️ **Merci de confirmer ta présence pour continuer !**",
                            view=view
                        )
                        logger.info(f"🍅 Boutons de présence envoyés à {member} (mode {mode})")
                    except discord.Forbidden:
                        logger.warning(f"⚠️ Impossible d'envoyer un DM à {member}")
                continue

            # Événement 2 : Rappel 1 minute avant la reprise
            if position_in_cycle >= (total_cycle - 60) and validated == 1 and current_cycle_index == cycles_completed:
                await db.update_participant_state(guild_id, user_id, validated=2)
                if member:
                    try:
                        await member.send(f"⏳ <@{user_id}> Plus qu'une minute avant la reprise ! N'oublie pas de valider ta présence en cliquant sur ✅ Continuer !")
                    except:
                        pass
                continue

            # Événement 3 : Fin du cycle -> Enregistrement normal (si validé)
            if current_cycle_index > cycles_completed and validated == 0:
                try:
                    await db.ajouter_temps(
                        user_id=user_id,
                        guild_id=guild_id,
                        temps_sec=work_duration,
                        mode=mode,
                        is_session_end=False
                    )
                    session_start = join_ts + cycles_completed * total_cycle
                    session_end = session_start + total_cycle
                    await db.record_session(
                        user_id=user_id,
                        guild_id=guild_id,
                        mode=mode,
                        work_time=work_duration,
                        pause_time=break_duration,
                        start_ts=session_start,
                        end_ts=session_end
                    )
                    await db.update_participant_state(guild_id, user_id, increment_cycles=True)
                    
                    if member:
                        try:
                            await member.send(
                                f"🔄 **Nouveau cycle !**\n"
                                f"C'est parti pour une nouvelle session de {format_seconds(work_duration)} !\n"
                                f"Cycle n°{cycles_completed + 2} 💪"
                            )
                        except:
                            pass
                except Exception as e:
                    logger.error(f"❌ Erreur lors de l'enregistrement du cycle: {e}")
                continue

            # Événement 4 : Délai de grâce expiré (Expulsion)
            grace_period = 10 * 60 if mode == "A" else 5 * 60
            if current_cycle_index > cycles_completed and position_in_cycle >= grace_period and validated > 0:
                # Calcul de la pénalité
                session_verified_time = cycles_completed * work_duration
                bonus_time = 0
                if session_verified_time < 3600:
                    bonus_time = 25 * 60
                elif session_verified_time < 7200:
                    bonus_time = 15 * 60
                
                if bonus_time > 0:
                    await db.ajouter_temps(user_id, guild_id, bonus_time, mode, is_session_end=True)
                    await db.record_session(
                        user_id=user_id,
                        guild_id=guild_id,
                        mode=mode,
                        work_time=bonus_time,
                        pause_time=0,
                        start_ts=now - bonus_time,
                        end_ts=now
                    )
                
                await db.remove_participant(guild_id, user_id)
                logger.info(f"🍅 {member} expulsé de la session pour inactivité (bonus: {bonus_time}s).")
                
                if member:
                    try:
                        msg = f"❌ **Session annulée pour inactivité.** Tu n'as pas validé ta présence après le délai de grâce.\n"
                        if bonus_time > 0:
                            msg += f"🎁 Je t'ai tout de même accordé **{format_seconds(bonus_time)}** de révision en guise de consolation pour ce dernier cycle !"
                        else:
                            msg += "Aucun temps supplémentaire n'a été ajouté car tu as déjà plus de 2h de révision validée."
                        await member.send(msg)
                    except:
                        pass

    @pomodoro_task.before_loop
    async def before_pomodoro_task(self):
        """Attendre que le bot soit prêt avant de démarrer la tâche"""
        await self.bot.wait_until_ready()
        logger.info("🍅 Pomodoro task prête à démarrer")

async def setup(bot):
    await bot.add_cog(Pomodoro(bot))
