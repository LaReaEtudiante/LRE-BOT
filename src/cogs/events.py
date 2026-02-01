# ==========================
# LRE-BOT/src/cogs/events.py
# ==========================
import discord
from discord.ext import commands
import time
import os
import traceback
import asyncio
from collections import deque
from core import db


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # recent message cache to avoid processing duplicates (per (author_id, channel_id))
        # Structure: { (author_id, channel_id): {"content": str, "last_ts": int, "message_ids": set(int)} }
        self._recent_messages = {}
        self._debounce_lock = asyncio.Lock()
        # configuration
        self._debounce_window = 3  # seconds: if same content within this window -> consider duplicate
        self._max_message_ids = 6  # keep last N message ids per key
        self._prune_interval = 20  # seconds: entries older than this will be pruned
        self._max_cache_size = 1000  # safety cap

        # ensure we only call process_commands once per message id (protects against duplicate on_message calls)
        self._processed_ids_deque = deque(maxlen=5000)
        self._processed_ids_set = set()

        # debug flag: si True imprime des logs de debug (garde False en prod)
        self._debug = False

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"[INFO] {self.bot.user} connecté ✅ PID={os.getpid()}")
        await db.init_db()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await db.upsert_user(
            user_id=member.id,
            username=member.name,
            join_date=int(time.time())
        )
        print(f"[INFO] {member} a rejoint, ajouté à la DB")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        async with db.aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute(
                "UPDATE users SET leave_date=? WHERE user_id=?",
                (int(time.time()), member.id),
            )
            await conn.commit()
        print(f"[INFO] {member} a quitté, leave_date mis à jour")

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
            # DM: processer et sortir
            # Mais protéger contre double-invocation via message.id
            await self._safe_process_commands(message)
            return

        author_id = message.author.id
        channel_id = message.channel.id
        # normaliser le contenu pour comparaison
        try:
            content = message.clean_content.strip()
        except Exception:
            content = (message.content or "").strip()

        now = int(time.time())
        key = (author_id, channel_id)

        # Debounce / dedupe logic with a lock to avoid concurrent races
        is_duplicate = False
        async with self._debounce_lock:
            entry = self._recent_messages.get(key)
            if entry:
                # exact same message id already processed for this key
                if message.id in entry.get("message_ids", set()):
                    is_duplicate = True
                    if self._debug:
                        print(f"[DEDUPE] message id {message.id} déjà dans entry.message_ids pour {key}")
                else:
                    last_content = entry.get("content", "")
                    last_ts = entry.get("last_ts", 0)
                    # same content inside debounce window => consider duplicate
                    if last_content == content and (now - last_ts) < self._debounce_window:
                        # still record message id to avoid reprocessing further duplicates
                        entry["message_ids"].add(message.id)
                        # keep only last N ids
                        if len(entry["message_ids"]) > self._max_message_ids:
                            ids = list(entry["message_ids"])
                            ids = ids[-self._max_message_ids:]
                            entry["message_ids"] = set(ids)
                        is_duplicate = True
                        if self._debug:
                            print(f"[DEDUPE] contenu identique dans fenêtre pour {key} ({message.id})")
                    else:
                        # not considered duplicate: update entry
                        entry["content"] = content
                        entry["last_ts"] = now
                        entry["message_ids"].add(message.id)
                        if len(entry["message_ids"]) > self._max_message_ids:
                            ids = list(entry["message_ids"])
                            ids = ids[-self._max_message_ids:]
                            entry["message_ids"] = set(ids)
                        if self._debug:
                            print(f"[DEDUPE] nouveau contenu pour {key}, mise à jour entry")
            else:
                # new entry
                self._recent_messages[key] = {
                    "content": content,
                    "last_ts": now,
                    "message_ids": {message.id},
                }
                if self._debug:
                    print(f"[DEDUPE] nouvelle entree pour {key} with message {message.id}")

            # prune old entries if cache grows or periodically for stale entries
            if len(self._recent_messages) > self._max_cache_size:
                cutoff = now - self._prune_interval
                for k, v in list(self._recent_messages.items()):
                    if v.get("last_ts", 0) < cutoff:
                        del self._recent_messages[k]
                        if self._debug:
                            print(f"[PRUNE] removed stale entry for {k}")

        if is_duplicate:
            # doublon identifié : on ignore sans appeler process_commands
            if self._debug:
                print(f"[DEDUPE] Ignoring duplicate message {message.id} from {message.author} in {message.channel}")
            return

        # Gérer les stickies de manière robuste (ne doit jamais empêcher process_commands)
        try:
            guild_id = message.guild.id
            channel_id = message.channel.id
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
            print(f"[WARN] Erreur lors de la gestion du sticky: {e}")

        # Appeler process_commands mais de façon sûre (une seule fois par message.id)
        await self._safe_process_commands(message)

    async def _safe_process_commands(self, message: discord.Message):
        """Appelle bot.process_commands(message) en s'assurant que c'est fait une seule fois par message.id."""
        async with self._debounce_lock:
            if message.id in self._processed_ids_set:
                if self._debug:
                    print(f"[SAFE] message {message.id} déjà traité -> skip process_commands")
                return
            # enregistrer comme traité
            self._processed_ids_set.add(message.id)
            self._processed_ids_deque.append(message.id)
            # si deque a évincement, enlever de set (deque gère la longueur max)
            while len(self._processed_ids_deque) > self._processed_ids_deque.maxlen:
                try:
                    old = self._processed_ids_deque.popleft()
                    self._processed_ids_set.discard(old)
                except Exception:
                    break

        # Hors du lock, appeler process_commands (peut être long)
        try:
            if self._debug:
                print(f"[SAFE] process_commands pour message {message.id} by {message.author} in {message.channel}")
            await self.bot.process_commands(message)
        except Exception as e:
            # log complet (on_command_error s'occupera d'envoyer un message utilisateur)
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            print(f"[ERROR] Erreur lors de process_commands pour message {message.id}:\n{tb}")

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
