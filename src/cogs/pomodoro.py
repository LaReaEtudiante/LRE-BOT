import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
from core import db
from utils.time_format import format_seconds
import discord.ui


class PomodoroCog(commands.Cog):
    """Gestion des boucles Pomodoro (modes A et B)"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pomodoro_loop.start()

    def cog_unload(self):
        """Arrête les tâches quand le cog est déchargé"""
        self.pomodoro_loop.cancel()

class PresenceView(discord.ui.View):
    def __init__(self, bot, guild_id, user_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id

    @discord.ui.button(label="Présent ✅", style=discord.ButtonStyle.success)
    async def confirm_presence(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce message ne vous est pas destiné.", ephemeral=True)
            return
            
        await db.validate_presence(self.guild_id, self.user_id)
        
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="✅ Présence confirmée ! Bon courage pour la suite de ta révision.", view=self)

    @discord.ui.button(label="Quitter ❌", style=discord.ButtonStyle.danger)
    async def leave_session(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce message ne vous est pas destiné.", ephemeral=True)
            return

        join_row = await db.remove_participant(self.guild_id, self.user_id)
        if join_row and join_row[0] is not None:
            join_ts, mode = join_row
            elapsed = db.now_ts() - join_ts
            await db.ajouter_temps(self.user_id, self.guild_id, elapsed, mode, is_session_end=True)
            content = f"👋 Tu as quitté la session. +{format_seconds(elapsed)} ajoutées."
        else:
            content = "Tu n'es plus dans la session."

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=content, view=self)


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

            for row in participants:
                if len(row) < 6:
                    user_id, join_ts, mode, validated = row[:4]
                    last_check_ts = join_ts
                    check_state = 0
                else:
                    user_id, join_ts, mode, validated, last_check_ts, check_state = row
                    
                start_time = datetime.fromtimestamp(join_ts, tz=timezone.utc)
                phase, remaining = self.get_phase_and_remaining(start_time, mode)

                now_ts = db.now_ts()
                elapsed_since_check = now_ts - last_check_ts
                
                user = self.bot.get_user(user_id)
                if not user:
                    continue

                if phase == "Pause" and elapsed_since_check >= 50 * 60:
                    if check_state == 0:
                        try:
                            view = PresenceView(self.bot, guild.id, user_id)
                            await user.send(
                                "🔔 **Vérification de présence**\n"
                                "Cela fait plus d'une heure que tu révises. Es-tu toujours là ? "
                                "Clique sur le bouton ci-dessous pour confirmer ta présence avant la fin de la pause, "
                                "sinon ta session sera arrêtée.",
                                view=view
                            )
                            await db.update_check_state(guild.id, user_id, 1)
                        except discord.Forbidden:
                            if channel:
                                await channel.send(f"⚠️ {user.mention}, je ne peux pas t'envoyer de MP. Tu as 1 heure de révision, clique sur ✅ pour continuer !", view=PresenceView(self.bot, guild.id, user_id))
                                await db.update_check_state(guild.id, user_id, 1)

                    elif check_state == 1 and remaining <= 60:
                        try:
                            view = PresenceView(self.bot, guild.id, user_id)
                            await user.send(
                                "⚠️ **Dernier avertissement !**\n"
                                "Ta pause se termine bientôt. Si tu ne confirmes pas ta présence, tu seras expulsé(e) de la session.",
                                view=view
                            )
                            await db.update_check_state(guild.id, user_id, now_ts)
                        except discord.Forbidden:
                            if channel:
                                await channel.send(f"🚨 {user.mention}, dernier avertissement avant expulsion !", view=PresenceView(self.bot, guild.id, user_id))
                                await db.update_check_state(guild.id, user_id, now_ts)

                elif phase == "Travail" and check_state > 0:
                    if check_state == 1:
                        await db.update_check_state(guild.id, user_id, now_ts)
                    elif check_state > 1 and (now_ts - check_state) >= 5 * 60:
                        join_row = await db.remove_participant(guild.id, user_id)
                        if join_row:
                            time_to_add = (last_check_ts - join_ts) + (50 * 60)
                            if time_to_add < 0: time_to_add = 0
                            await db.ajouter_temps(user_id, guild.id, time_to_add, mode, is_session_end=True)
                            
                            try:
                                await user.send(f"❌ Tu as été expulsé(e) de la session pour inactivité. +{format_seconds(time_to_add)} ajoutées.")
                            except discord.Forbidden:
                                if channel:
                                    await channel.send(f"❌ {user.mention} a été expulsé(e) pour inactivité.")

    @pomodoro_loop.before_loop
    async def before_pomodoro(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(PomodoroCog(bot))
