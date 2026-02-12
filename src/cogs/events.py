# ==========================
# LRE-BOT/src/cogs/events.py
# ==========================
import discord
from discord.ext import commands
import time
import os
import traceback
from core import db


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # -------------------------
        # CRITICAL DEBOUNCE BLOCK
        # -------------------------
        DEBOUNCE_WINDOW = 5  # secondes — NE PAS CHANGER SANS CONSENTEMENT
        _DEBOUNCE_GUARD = "UNMODIFIED:v1"
        # -------------------------

        self._recent_messages = {}
        self._debounce_window = DEBOUNCE_WINDOW
        self._debounce_guard = _DEBOUNCE_GUARD

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"[INFO] {self.bot.user} connecté ✅ PID={os.getpid()}")
        if getattr(self, "_debounce_guard", None) != "UNMODIFIED:v1":
            print("[WARN] Le bloc DEBOUNCE a été modifié ! Ceci peut causer des doublons.")
        await db.init_db()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await db.upsert_user(user_id=member.id, username=member.name, join_date=int(time.time()))
        print(f"[INFO] {member} a rejoint, ajouté à la DB")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        async with db.aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute("UPDATE users SET leave_date=? WHERE user_id=?", (int(time.time()), member.id))
            await conn.commit()
        print(f"[INFO] {member} a quitté, leave_date mis à jour")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if message.guild is None or message.channel is None:
            await self.bot.process_commands(message)
            return

        # ⚠️ CORRECTION : Ne pas bloquer les commandes avec le debounce
        # Si le message commence par le préfixe de commande, on le traite immédiatement
        if message.content.startswith(self.bot.command_prefix):
            await self.bot.process_commands(message)
            return

        # Le debounce s'applique uniquement aux messages normaux (non-commandes)
        key = (message.author.id, message.channel.id, message.content.strip())
        now = int(time.time())
        last = self._recent_messages.get(key)
        window = getattr(self, "_debounce_window", 5)

        if last and now - last < window:
            return

        self._recent_messages[key] = now

        if len(self._recent_messages) > 500:
            cutoff = now - (window * 3)
            for k, ts in list(self._recent_messages.items()):
                if ts < cutoff:
                    del self._recent_messages[k]

        guild_id = message.guild.id
        channel_id = message.channel.id

        try:
            sticky = await db.get_sticky(guild_id, channel_id)
            if sticky:
                try:
                    old_msg = await message.channel.fetch_message(sticky[0])
                    await old_msg.delete()
                except Exception:
                    pass
                content = sticky[1]
                new_sticky = await message.channel.send(content)
                try:
                    await db.set_sticky(guild_id, channel_id, new_sticky.id, content, sticky[2] if len(sticky) > 2 else None)
                except Exception:
                    pass
        except Exception as e:
            print(f"[WARN] Erreur lors de la gestion du sticky: {e}")

        await self.bot.process_commands(message)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Tu n'as pas la permission d'utiliser cette commande.")
            return
        if isinstance(error, commands.CheckFailure):
            return

        print(f"[ERROR] {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        await ctx.send("❌ Une erreur s'est produite.")


async def setup(bot):
    await bot.add_cog(Events(bot))
