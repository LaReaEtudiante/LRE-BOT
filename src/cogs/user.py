# ==========================
# LRE-BOT/src/cogs/user.py
# ==========================
import discord
from discord.ext import commands
from core import db, config
from utils.time_format import format_seconds
from utils import checks

class UserCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ... (help, joina/joinb/leave/me/stats code inchangé) ...

    # ─── Leaderboard ───────────────────────────────────────
    @commands.command(name="leaderboard", help="Classements divers")
    @checks.in_pomodoro_channel()
    @checks.roles_are_set()
    @checks.not_in_maintenance()
    async def leaderboard(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        lb = await db.get_leaderboards(guild_id)

        embed = discord.Embed(
            title="🏆 Leaderboard",
            color=discord.Color.gold()
        )

        for title, entries in lb.items():
            if not entries:
                value = "aucune donnée"
            else:
                lines = []
                for i, row in enumerate(entries, start=1):
                    # row peut être (user_id, val) ou (user_id, val1, val2)
                    try:
                        uid = row[0]
                        # Récupérer display_name de façon sûre
                        try:
                            user = await self.bot.fetch_user(uid)
                            display = user.display_name
                        except Exception:
                            user_obj = self.bot.get_user(uid)
                            display = user_obj.display_name if user_obj else f"<{uid}>"

                        # Construire le label selon le nombre de colonnes
                        if len(row) == 2:
                            val = row[1]
                            label = format_seconds(val) if isinstance(val, int) else str(val)
                        elif len(row) == 3:
                            # ex: (user_id, streak_current, streak_best)
                            val1 = row[1]
                            val2 = row[2]
                            # Afficher streak_best (val2) et streak_current entre parenthèses
                            label = f"{val2} (actuel {val1})"
                        else:
                            # fallback
                            label = " / ".join(str(x) for x in row[1:])

                        lines.append(f"{i}. {display} — {label}")
                    except Exception:
                        # en cas d'erreur pour une ligne, on l'affiche avec l'ID
                        lines.append(f"{i}. <{row[0]}> — erreur de lecture")

                value = "\n".join(lines)

            embed.add_field(name=title, value=value, inline=False)

        await ctx.send(embed=embed)
