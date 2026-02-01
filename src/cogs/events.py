# ==========================
# LRE-BOT/src/cogs/events.py
# ==========================
import discord
from discord.ext import commands
import time
import os
import traceback
from core import db


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # recent message cache to avoid processing duplicates (author_id, channel_id, content) -> timestamp
        self._recent_messages = {}

    # ─── Quand le bot est prêt ───────────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        # Affiche le PID pour détecter plusieurs instances (utile en debug)
        print(f"[INFO] {self.bot.user} connecté ✅ PID={os.getpid()}")
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
        """Vérifie les stickies et relance la détection de commandes.
        Protection contre les doublons de messages/commandes venant du même auteur
        dans le même salon (même contenu) sur une courte fenêtre pour éviter réponses en double.
        """
        # Ignorer les bots
        if message.author.bot:
            return

        # Si message en DM : on laisse le traitement normal des commandes et on quitte
        if message.guild is None or message.channel is None:
            await self.bot.process_commands(message)
            return

        # Debounce key
        key = (message.author.id, message.channel.id, message.content.strip())
        now = int(time.time())
        last = self._recent_messages.get(key)
        if last and now - last < 2:
            # doublon récent : ignorer pour éviter double traitement
            return
        self._recent_messages[key] = now
        # Nettoyage léger des entrées trop vieilles
        if len(self._recent_messages) > 200:
            cutoff = now - 10
            for k, ts in list(self._recent_messages.items()):
                if ts < cutoff:
                    del self._recent_messages[k]

        guild_id = message.guild.id
        channel_id = message.channel.id

        # Gérer les stickies de manière robuste (ne doit jamais empêcher process_commands)
        try:
            sticky = await db.get_sticky(guild_id, channel_id)
            if sticky:
                # sticky retourne typiquement (message_id, content, author_id) ou (message_id, text, requested_by)
                try:
                    old_msg = await message.channel.fetch_message(sticky[0])  # message_id
                    await old_msg.delete()
                except Exception:
                    pass  # si l'ancien sticky n'existe plus, on ignore

                # content/text est en position 1
                content = sticky[1]
                new_sticky = await message.channel.send(content)

                # Mettre à jour en DB (db.set_sticky gère le fallback)
                try:
                    await db.set_sticky(guild_id, channel_id, new_sticky.id, content, sticky[2] if len(sticky) > 2 else None)
                except Exception:
                    # Si la mise à jour échoue, on l'ignore pour ne pas casser on_message
                    pass
        except Exception as e:
            # Logguer l'erreur pour debug mais ne pas bloquer la suite
            print(f"[WARN] Erreur lors de la gestion du sticky: {e}")

        # 🔥 LIGNE CRUCIALE : permet de traiter les commandes (*help, *join, etc.)
        await self.bot.process_commands(message)

    # ─── Gestion des erreurs de commandes ─────────────────────────────
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):

            # ─── Cas : rôles Pomodoro manquants ─────────────────────────
            if str(error) == "NO_POMODORO_ROLES":
                # (le code de gestion que tu avais précédemment)
                # ...
                await ctx.send("⚠️ Le bot n’est pas configuré correctement. Contactez un administrateur.")
                return

            # ─── Cas : salon Pomodoro manquant ───────────────────────────
            if str(error) == "NO_POMODORO_CHANNEL":
                # (le code de gestion que tu avais précédemment)
                await ctx.send("⚠️ Le bot n’est pas configuré correctement. Contactez un administrateur.")
                return

            # CheckFailure non spécifique : renvoyer une info utile
            await ctx.send("❌ Vous ne pouvez pas exécuter cette commande (vérifiez la configuration et vos permissions).")
            return

        # Pour toutes les autres erreurs : log complet + message utilisateur
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        print(f"[ERROR] Une erreur est survenue durant l'exécution d'une commande:\n{tb}")

        try:
            await ctx.send("❌ Une erreur interne est survenue lors du traitement de la commande. Les logs ont été écrits côté serveur.")
        except Exception:
            pass


auto async def setup(bot):
    await bot.add_cog(Events(bot))
