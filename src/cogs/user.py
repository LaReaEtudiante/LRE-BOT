# ==========================
# LRE-BOT/src/cogs/user.py
# ==========================
from discord.ext import commands

class UserCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="me")
    async def me(self, ctx):
        await ctx.send("📊 Voici tes stats (placeholder)")

async def setup(bot):
    await bot.add_cog(UserCog(bot))
