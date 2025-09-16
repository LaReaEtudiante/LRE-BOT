import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
from core import db
from utils.time_format import format_seconds


class PomodoroCog(commands.Cog):
    """Gestion des boucles Pomodoro (modes A et B)"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pomodoro_loop.start()

    def cog_unload(self):
        """Arrête les tâches quand le cog est déchargé"""
        self.pomodoro_loop.cancel()

    # ─── Configurations des phases ─────────────────────────────
    MODES = {
        "A": [("Travail", 50 * 60), ("Pause", 10 * 60)],
        "B": [("Travail", 25 * 60), ("Pause", 5 * 60),
              ("Travail", 25 * 60), ("Pause", 5 * 60)],
    }

    # ─── Calcul de phase en cours ──────────────────────────────
    @classmethod
    def get_phase_and_remaining(cls, start_time: datetime, mode: str):
        phases = cls.MODES.get(mode)
        if not phases:
            return "Inconnu", 0

        elapsed = int((datetime.now(timezone.utc) - start_time).total_seconds())
        cycle_len = sum(duration for _, duration in phases)
        elapsed %= cycle_len

        for name, duration in phases:
            if elapsed < duration:
                return name, duration - elapsed
            elapsed -= duration

        return "Inconnu", 0

    # ─── Boucle principale ─────────────────────────────────────
    @tasks.loop(seconds=60)
    async def pomodoro_loop(self):
        """Boucle qui vérifie l’état des participants toutes les minutes"""
        for guild in self.bot.guilds:
            participants = await db.get_participants(guild.id)
            if not participants:
                continue

            chan_id = await db.get_setting("channel_id")
            if not chan_id:
                continue

            channel = guild.get_channel(int(chan_id))
            if not channel:
                continue

            for user_id, join_ts, mode, validated in participants:
                start_time = datetime.fromtimestamp(join_ts, tz=timezone.utc)
                phase, remaining = self.get_phase_and_remaining(start_time, mode)

                # Exemple: message de debug → tu peux le remplacer par un sticky
                # await channel.send(f"🔄 {self.bot.get_user(user_id)} est en {phase}, reste {format_seconds(remaining)}")

    @pomodoro_loop.before_loop
    async def before_pomodoro(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(PomodoroCog(bot))
