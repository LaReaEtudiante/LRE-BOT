# ==========================
# LRE-BOT/src/cogs/events.py
# ==========================
import discord
from discord.ext import commands
import time
from core import db


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── Quand le bot est prêt ───────────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        print(f"[INFO] {self.bot.user} connecté ✅")
        await db.init_db()

    # ─── Quand un membre rejoint ─────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await db.upsert_user(
            user_id=member.id,
            username=member.name,
            join_date=int(time.time())
        )
        print(f"[INFO] {member} a rejoint, ajouté à la DB")

    # ─── Quand un membre quitte ──────────────────────────────────
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        async with db.aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute(
                "UPDATE users SET leave_date=? WHERE user_id=?",
                (int(time.time()), member.id),
            )
            await conn.commit()
        print(f"[INFO] {member} a quitté, leave_date mis à jour")

    # ─── Sticky auto-refresh ─────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return  # ignorer les bots

        guild_id = message.guild.id
        channel_id = message.channel.id

        # Vérifier si un sticky est défini pour ce salon
        sticky = await db.get_sticky(guild_id, channel_id)
        if not sticky:
            return

        sticky_id, content, author_id = sticky

        try:
            old_msg = await message.channel.fetch_message(sticky_id)
            await old_msg.delete()
        except Exception:
            pass  # si l'ancien sticky n'existe plus, on ignore

        # Reposter le sticky
        new_sticky = await message.channel.send(content)

        # Mettre à jour en DB
        await db.set_sticky(guild_id, channel_id, new_sticky.id, content, author_id)


async def setup(bot):
    await bot.add_cog(Events(bot))
