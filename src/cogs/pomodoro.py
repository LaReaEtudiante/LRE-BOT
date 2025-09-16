# ==========================
# LRE-BOT/src/cogs/pomodoro.py
# ==========================
from discord.ext import commands

class PomodoroCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="joina")
    async def joina(self, ctx):
        await ctx.send("⏳ Tu as rejoint le mode A (placeholder)")

async def setup(bot):
    await bot.add_cog(PomodoroCog(bot))
