# ==========================
# LRE-BOT/src/cogs/events.py
# ==========================
import discord
from discord.ext import commands
import time
import os
import traceback
from core import db
import logging

logger = logging.getLogger('LRE-BOT.events')


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(f"✅ {self.bot.user} connecté à Discord (PID={os.getpid()})")
        await db.init_db()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await db.upsert_user(user_id=member.id, username=member.name, join_date=int(time.time()))
        logger.info(f"✅ {member} a rejoint le serveur, ajouté à la DB")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        async with db.aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute("UPDATE users SET leave_date=? WHERE user_id=?", (int(time.time()), member.id))
            await conn.commit()
        logger.info(f"✅ {member} a quitté le serveur, leave_date mis à jour")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if message.content.startswith(self.bot.command_prefix):
            return
        
        if message.guild is None or message.channel is None:
            return
        
        guild_id = message.guild.id
        channel_id = message.channel.id

        # Gestion des sticky messages
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
            logger.error(f"❌ Erreur lors de la gestion du sticky: {e}")

    @commands.Cog.listener()
    async def on_command(self, ctx):
        if ctx.command:
            logger.info(f"⏳ Exécution de la commande *{ctx.command.name} par {ctx.author}")

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        if ctx.command:
            logger.info(f"✅ Commande *{ctx.command.name} exécutée avec succès par {ctx.author}")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            logger.warning(f"⚠️ Commande introuvable tentée par {ctx.author} : {ctx.message.content}")
            return
            
        if isinstance(error, commands.MissingRequiredArgument):
            logger.warning(f"⚠️ {ctx.author} a oublié l'argument '{error.param.name}' pour la commande *{ctx.command.name if ctx.command else 'unknown'}")
            await ctx.send(f"❌ Il manque un argument obligatoire (`{error.param.name}`). Regarde l'aide pour cette commande.")
            return

        if isinstance(error, commands.BadArgument):
            logger.warning(f"⚠️ {ctx.author} a fourni un argument invalide pour la commande *{ctx.command.name if ctx.command else 'unknown'}")
            await ctx.send(f"❌ Un argument fourni n'est pas valide. Vérifie ta commande.")
            return

        if isinstance(error, commands.CommandOnCooldown):
            logger.warning(f"⚠️ {ctx.author} est en cooldown pour *{ctx.command.name if ctx.command else 'unknown'} ({error.retry_after:.1f}s restantes)")
            await ctx.send(f"⏳ Doucement ! Attends encore {error.retry_after:.1f} secondes avant d'utiliser cette commande.")
            return

        if isinstance(error, commands.MissingPermissions):
            logger.warning(f"⚠️ {ctx.author} n'a pas les permissions requises pour *{ctx.command.name if ctx.command else 'unknown'}")
            await ctx.send("❌ Tu n'as pas la permission d'utiliser cette commande.")
            return
            
        if isinstance(error, commands.CheckFailure):
            if str(error) == "MAINTENANCE_ACTIVE":
                logger.warning(f"⚠️ Commande *{ctx.command.name if ctx.command else 'unknown'} refusée à {ctx.author} (Maintenance active)")
                if ctx.author.guild_permissions.administrator:
                    await ctx.send("⚠️ Le mode maintenance est actif. Les commandes sont désactivées. Désactivez le mode maintenance avec `*maintenance` pour utiliser le bot.")
                else:
                    await ctx.send("⚠️ Le bot est en maintenance — les commandes sont temporairement indisponibles. Réessayez plus tard.")
                return
            
            logger.warning(f"⚠️ {ctx.author} n'a pas validé les vérifications pour *{ctx.command.name if ctx.command else 'unknown'}")
            return

        # Any other exception that was not caught
        logger.error(f"❌ [ERREUR CRITIQUE] Une exception non gérée a été déclenchée par la commande *{ctx.command.name if ctx.command else 'unknown'} utilisée par {ctx.author}")
        logger.error(f"Détails: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        await ctx.send("❌ Une erreur interne est survenue lors de l'exécution de cette commande. Le problème a été logué.")


async def setup(bot):
    await bot.add_cog(Events(bot))
