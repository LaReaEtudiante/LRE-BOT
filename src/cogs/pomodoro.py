# ==========================
# LRE-BOT/src/cogs/pomodoro.py
# ==========================
import discord
from discord.ext import commands, tasks
from core import db
from utils.time_format import format_seconds
import asyncio
import logging

logger = logging.getLogger('LRE-BOT.pomodoro')

# Configuration des cycles Pomodoro
POMODORO_MODES = {
    "A": {"work": 50 * 60, "break": 10 * 60},  # 50 min travail, 10 min pause
    "B": {"work": 25 * 60, "break": 5 * 60}     # 25 min travail, 5 min pause
}


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
        logger.debug("🍅 Pomodoro task - Vérification des sessions")
        
        # Récupérer tous les participants actifs
        async with db.aiosqlite.connect(db.DB_PATH) as conn:
            async with conn.execute("""
                SELECT guild_id, user_id, join_timestamp, mode 
                FROM participants
            """) as cursor:
                participants = await cursor.fetchall()

        now = db.now_ts()

        for guild_id, user_id, join_ts, mode in participants:
            elapsed = now - join_ts
            cycle = POMODORO_MODES.get(mode)
            
            if not cycle:
                continue

            work_duration = cycle["work"]
            break_duration = cycle["break"]
            total_cycle = work_duration + break_duration

            # Calculer où on en est dans le cycle
            position_in_cycle = elapsed % total_cycle

            # Phase de travail terminée ?
            if position_in_cycle >= work_duration and (position_in_cycle - 60) < work_duration:
                # On vient de finir une phase de travail
                try:
                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        member = guild.get_member(user_id)
                        if member:
                            # Envoyer notification de pause
                            try:
                                await member.send(
                                    f"⏸️ **Pause bien méritée !**\n"
                                    f"Tu as terminé une session de {format_seconds(work_duration)} !\n"
                                    f"Prends {format_seconds(break_duration)} de repos. 🌟"
                                )
                                logger.info(f"🍅 Notification pause envoyée à {member} (mode {mode})")
                            except discord.Forbidden:
                                logger.warning(f"⚠️ Impossible d'envoyer un DM à {member}")
                except Exception as e:
                    logger.error(f"❌ Erreur lors de la notification de pause: {e}")

            # Cycle complet terminé ? (fin de pause)
            if position_in_cycle < 60 and elapsed >= total_cycle:
                # On vient de finir un cycle complet (travail + pause)
                try:
                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        member = guild.get_member(user_id)
                        if member:
                            # Enregistrer le cycle complet
                            await db.ajouter_temps(
                                user_id=user_id,
                                guild_id=guild_id,
                                temps_sec=work_duration,
                                mode=mode,
                                is_session_end=False  # Pas encore la fin totale
                            )

                            # Enregistrer la session détaillée
                            session_start = join_ts + (elapsed // total_cycle - 1) * total_cycle
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

                            # Notification de nouveau cycle
                            try:
                                nb_cycles = elapsed // total_cycle
                                await member.send(
                                    f"🔄 **Nouveau cycle !**\n"
                                    f"C'est parti pour une nouvelle session de {format_seconds(work_duration)} !\n"
                                    f"Cycle n°{nb_cycles + 1} 💪"
                                )
                                logger.info(f"🍅 Cycle {nb_cycles} terminé pour {member} (mode {mode})")
                            except discord.Forbidden:
                                pass
                except Exception as e:
                    logger.error(f"❌ Erreur lors de l'enregistrement du cycle: {e}")

    @pomodoro_task.before_loop
    async def before_pomodoro_task(self):
        """Attendre que le bot soit prêt avant de démarrer la tâche"""
        await self.bot.wait_until_ready()
        logger.info("🍅 Pomodoro task prête à démarrer")


async def setup(bot):
    await bot.add_cog(Pomodoro(bot))
