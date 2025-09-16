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


async def setup(bot):
    await bot.add_cog(Events(bot))
