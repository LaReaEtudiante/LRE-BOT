# ==========================
# LRE-BOT/src/cogs/sticky.py
# ==========================
from discord.ext import commands

class StickyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="colle")
    async def colle(self, ctx, *, message: str):
        await ctx.send(f"📌 Message collé : {message}")

async def setup(bot):
    await bot.add_cog(StickyCog(bot))
