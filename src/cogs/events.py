# ==========================
# LRE-BOT/src/cogs/events.py
# ==========================
from discord.ext import commands

class EventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{self.bot.user} est connecté et prêt !")

async def setup(bot):
    await bot.add_cog(EventsCog(bot))
