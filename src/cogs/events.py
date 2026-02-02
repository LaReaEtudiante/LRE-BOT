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

        # -------------------------
        # CRITICAL DEBOUNCE BLOCK
        # -------------------------
        DEBOUNCE_WINDOW = 5  # secondes — NE PAS CHANGER SANS CONSENTEMENT
        _DEBOUNCE_GUARD = "UNMODIFIED:v1"
        # -------------------------

        self._recent_messages = {}
        self._debounce_window = DEBOUNCE_WINDOW
        self._debounce_guard = _DEBOUNCE_GUARD

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"[INFO] {self.bot.user} connecté ✅ PID={os.getpid()}")
        if getattr(self, "_debounce_guard", None) != "UNMODIFIED:v1":
            print("[WARN] Le bloc DEBOUNCE a été modifié ! Ceci peut causer des doublons.")
        await db.init_db()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await db.upsert_user(user_id=member.id, username=member.name, join_date=int(time.time()))
        print(f"[INFO] {member} a rejoint, ajouté à la DB")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        async with db.aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute("UPDATE users SET leave_date=? WHERE user_id=?", (int(time.time()), member.id))
            await conn.commit()
        print(f"[INFO] {member} a quitté, leave_date mis à jour")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if message.guild is None or message.channel is None:
            await self.bot.process_commands(message)
            return

        key = (message.author.id, message.channel.id, message.content.strip())
        now = int(time.time())
        last = self._recent_messages.get(key)
        window = getattr(self, "_debounce_window", 5)

        if last and now - last < window:
            return

        self._recent_messages[key] = now

        if len(self._recent_messages) > 500:
            cutoff = now - (window * 3)
            for k, ts in list(self._recent_messages.items()):
                if ts < cutoff:
                    del self._recent_messages[k]

        guild_id = message.guild.id
        channel_id = message.channel.id

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
            print(f"[WARN] Erreur lors de la gestion du sticky: {e}")

        await self.bot.process_commands(message)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            if str(error) == "MAINTENANCE_ACTIVE":
                if ctx.author.guild_permissions.administrator:
                    await ctx.send("⚠️ Le mode maintenance est actif. Les commandes sont désactivées. Désactivez le mode maintenance avec `*maintenance` pour utiliser le bot.")
                else:
                    await ctx.send("⚠️ Le bot est en maintenance — les commandes sont temporairement indisponibles. Réessayez plus tard.")
                return

            if str(error) == "NO_POMODORO_ROLES":
                if ctx.author.guild_permissions.administrator:
                    msg = await ctx.send(
                        "⚠️ Aucun rôle Pomodoro trouvé.\n"
                        "Voulez-vous que je les crée ?\n"
                        "➡️ Mode A : par défaut `50-10`\n"
                        "➡️ Mode B : par défaut `25-5`\n\n"
                        "✅ : créer avec noms par défaut\n"
                        "❌ : annuler\n"
                        "✏️ : personnaliser les noms"
                    )
                    for emoji in ["✅", "❌", "✏️"]:
                        await msg.add_reaction(emoji)

                    def check(reaction, user):
                        return (
                            user == ctx.author
                            and str(reaction.emoji) in ["✅", "❌", "✏️"]
                            and reaction.message.id == msg.id
                        )

                    try:
                        reaction, _ = await self.bot.wait_for("reaction_add", check=check, timeout=60.0)
                    except Exception:
                        await ctx.send("⏳ Temps écoulé, opération annulée.")
                        return

                    if str(reaction.emoji) == "❌":
                        await ctx.send("❌ Création des rôles annulée.")
                        return

                    if str(reaction.emoji) == "✅":
                        role_a = await ctx.guild.create_role(name="Mode A (50-10)")
                        role_b = await ctx.guild.create_role(name="Mode B (25-5)")
                        await db.set_setting("pomodoro_role_A", str(role_a.id))
                        await db.set_setting("pomodoro_role_B", str(role_b.id))
                        await ctx.send("✅ Rôles créés et enregistrés avec succès !")
                        return

                    if str(reaction.emoji) == "✏️":
                        await ctx.send("✏️ Envoyez le nom du rôle **Mode A** (ou tapez `annuler`).")

                        def check_msg(m):
                            return m.author == ctx.author and m.channel == ctx.channel

                        msg_a = await self.bot.wait_for("message", check=check_msg)
                        if msg_a.content.lower() == "annuler":
                            await ctx.send("❌ Création annulée.")
                            return
                        role_a = await ctx.guild.create_role(name=msg_a.content)

                        await ctx.send("✏️ Envoyez le nom du rôle **Mode B** (ou tapez `annuler`).")
                        msg_b = await self.bot.wait_for("message", check=check_msg)
                        if msg_b.content.lower() == "annuler":
                            await ctx.send("❌ Création annulée.")
                            return
                        role_b = await ctx.guild.create_role(name=msg_b.content)

                        await db.set_setting("pomodoro_role_A", str(role_a.id))
                        await db.set_setting("pomodoro_role_B", str(role_b.id))
                        await ctx.send("✅ Rôles créés et enregistrés avec succès !")
                else:
                    await ctx.send("⚠️ Le bot n’est pas configuré correctement. Contactez un administrateur.")
                return

            if str(error) == "NO_POMODORO_CHANNEL":
                if ctx.author.guild_permissions.administrator:
                    msg = await ctx.send(
                        "⚠️ Aucun salon Pomodoro configuré.\n"
                        "Voulez-vous que je crée un salon `#pomodoro` ?\n\n"
                        "✅ : créer `#pomodoro`\n"
                        "❌ : annuler\n"
                        "✏️ : entrer un salon existant avec #nom"
                    )
                    for emoji in ["✅", "❌", "✏️"]:
                        await msg.add_reaction(emoji)

                    def check(reaction, user):
                        return (
                            user == ctx.author
                            and str(reaction.emoji) in ["✅", "❌", "✏️"]
                            and reaction.message.id == msg.id
                        )

                    try:
                        reaction, _ = await self.bot.wait_for("reaction_add", check=check, timeout=60.0)
                    except Exception:
                        await ctx.send("⏳ Temps écoulé, opération annulée.")
                        return

                    if str(reaction.emoji) == "❌":
                        await ctx.send("❌ Création du salon annulée.")
                        return

                    if str(reaction.emoji) == "✅":
                        channel = await ctx.guild.create_text_channel("pomodoro")
                        await db.set_setting("channel_id", str(channel.id))
                        await ctx.send(f"✅ Salon {channel.mention} créé et enregistré avec succès !")
                        return

                    if str(reaction.emoji) == "✏️":
                        await ctx.send("✏️ Envoyez le nom du salon existant (par ex. `#pomodoro-room`).")

                        def check_msg(m):
                            return m.author == ctx.author and m.channel == ctx.channel

                        msg_channel = await self.bot.wait_for("message", check=check_msg)
                        if not msg_channel.channel_mentions:
                            await ctx.send("⚠️ Aucun salon mentionné, opération annulée.")
                            return

                        channel = msg_channel.channel_mentions[0]
                        await db.set_setting("channel_id", str(channel.id))
                        await ctx.send(f"✅ Salon {channel.mention} enregistré avec succès !")
                else:
                    await ctx.send("⚠️ Le bot n’est pas configuré correctement. Contactez un administrateur.")
                return

            await ctx.send("❌ Vous ne pouvez pas exécuter cette commande (vérifiez la configuration et vos permissions).")
            return

        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        print(f"[ERROR] Une erreur est survenue durant l'exécution d'une commande:\n{tb}")

        try:
            await ctx.send("❌ Une erreur interne est survenue lors du traitement de la commande. Les logs ont été écrits côté serveur.")
        except Exception:
            pass

async def setup(bot):
    await bot.add_cog(Events(bot))
