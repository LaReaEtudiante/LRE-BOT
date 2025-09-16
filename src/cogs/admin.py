# ==========================
# LRE-BOT/src/cogs/admin.py
# ==========================
from discord.ext import commands

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="maintenance")
    async def maintenance(self, ctx):
        await ctx.send("⚙️ Mode maintenance activé/désactivé (placeholder)")

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
