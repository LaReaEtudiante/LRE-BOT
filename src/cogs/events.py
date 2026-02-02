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
        # IMPORTANT : NE PAS MODIFIER ce bloc sans coordination.
        # Ce bloc protège le bot contre le "rebounce" (double exécution
        # des commandes / réponses en double). Si tu changes ces valeurs,
        # le comportement anti‑doublon peut être cassé et provoquer des
        # réponses multiples gênantes pour les utilisateurs.
        #
        # - DEBOUNCE_WINDOW : durée (en secondes) pendant laquelle un
        #   message identique (même auteur, même salon, même contenu)
        #   sera ignoré s'il a déjà été traité.
        # - _DEBOUNCE_GUARD : marqueur pour détecter toute modification
        #   accidentelle du bloc (logguée au démarrage).
        #
        # Si tu veux modifier la fenêtre, contacte la personne en charge.
        DEBOUNCE_WINDOW = 5  # secondes — NE PAS CHANGER SANS CONSENTEMENT
        _DEBOUNCE_GUARD = "UNMODIFIED:v1"  # guard marker — used to detect edits
        # -------------------------
        # End CRITICAL DEBOUNCE BLOCK
        # -------------------------

        # recent message cache to avoid processing duplicates
        # key = (author_id, channel_id, normalized_content) -> last_timestamp
        self._recent_messages = {}

        # expose the constants for tests / runtime checks
        self._debounce_window = DEBOUNCE_WINDOW
        self._debounce_guard = _DEBOUNCE_GUARD

    # ─── Quand le bot est prêt ───────────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        # Affiche le PID pour détecter plusieurs instances (utile en debug)
        print(f"[INFO] {self.bot.user} connecté ✅ PID={os.getpid()}")

        # Vérifier l'intégrité du bloc debounce au démarrage
        if getattr(self, "_debounce_guard", None) != "UNMODIFIED:v1":
            print("[WARN] Le bloc DEBOUNCE a été modifié ! Ceci peut causer des doublons. "
                  "Vérifie src/cogs/events.py — section CRITICAL DEBOUNCE BLOCK.")
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

        # ---------------------------
        # Anti‑rebounce / debounce
        # ---------------------------
        # clé qui identifie un message "identique" : auteur + salon + contenu trimé
        key = (message.author.id, message.channel.id, message.content.strip())
        now = int(time.time())
        last = self._recent_messages.get(key)

        # utiliser la fenêtre définie dans le bloc critique
        window = getattr(self, "_debounce_window", 5)

        if last and now - last < window:
            # doublon récent : ignorer pour éviter double traitement
            # NB: on ne logge pas ce cas pour éviter flood dans les logs
            return

        # enregistrer la dernière occurrence
        self._recent_messages[key] = now

        # Nettoyage léger des entrées trop vieilles pour éviter mémoire croissante
        if len(self._recent_messages) > 500:
            cutoff = now - (window * 3)  # conserver une petite marge
            for k, ts in list(self._recent_messages.items()):
                if ts < cutoff:
                    del self._recent_messages[k]
        # ---------------------------
        # Fin Anti‑rebounce
        # ---------------------------

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
        # Gestion spécifique MAINTENANCE_ACTIVE (doit être traitée avant les autres CheckFailure)
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
                        reaction, _ = await self.bot.wait_for(
                            "reaction_add", check=check, timeout=60.0
                        )
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


async def setup(bot):
    await bot.add_cog(Events(bot))
