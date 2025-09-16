# ==========================
# LRE-BOT/src/cogs/user.py
# ==========================
import discord
from discord.ext import commands
import time
from core import db
from utils.time_format import format_seconds


class UserCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── Commande *me : voir ses stats ───────────────────────────
    @commands.command(name="me", help="Voir vos statistiques personnelles")
    async def me(self, ctx: commands.Context):
        user = await db.get_user(ctx.author.id)
        if not user:
            await ctx.send("⚠️ Vous n’avez encore aucune donnée enregistrée.")
            return

        total_time = format_seconds(user["total_time"])
        total_A = format_seconds(user["total_A"])
        total_B = format_seconds(user["total_B"])

        embed = discord.Embed(
            title=f"📊 Stats de {ctx.author.display_name}",
            color=discord.Color.blue()
        )
        embed.add_field(name="⏱️ Temps total", value=total_time, inline=False)
        embed.add_field(name="🅰️ Mode A", value=total_A, inline=True)
        embed.add_field(name="🅱️ Mode B", value=total_B, inline=True)
        embed.add_field(name="📚 Sessions", value=user["sessions_count"], inline=True)
        embed.add_field(name="🔥 Streak actuel", value=user["streak_current"], inline=True)
        embed.add_field(name="🏆 Meilleur streak", value=user["streak_best"], inline=True)

        await ctx.send(embed=embed)

    # ─── Commande *joina ─────────────────────────────────────────
    @commands.command(name="joina", help="Rejoindre une session en mode A (50-10)")
    async def joina(self, ctx: commands.Context):
        await db.add_participant(ctx.guild.id, ctx.author.id, "A")
        await ctx.send(f"✅ {ctx.author.mention} a rejoint le **mode A (50-10)** !")

    # ─── Commande *joinb ─────────────────────────────────────────
    @commands.command(name="joinb", help="Rejoindre une session en mode B (25-5)")
    async def joinb(self, ctx: commands.Context):
        await db.add_participant(ctx.guild.id, ctx.author.id, "B")
        await ctx.send(f"✅ {ctx.author.mention} a rejoint le **mode B (25-5)** !")

    # ─── Commande *leave ─────────────────────────────────────────
    @commands.command(name="leave", help="Quitter la session en cours")
    async def leave(self, ctx: commands.Context):
        removed = await db.remove_participant(ctx.guild.id, ctx.author.id)
        if removed:
            await ctx.send(f"👋 {ctx.author.mention} a quitté sa session.")
        else:
            await ctx.send("⚠️ Vous n’êtes pas dans une session.")


async def setup(bot):
    await bot.add_cog(UserCommands(bot))
