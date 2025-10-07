# ==========================
# LRE-BOT/src/cogs/events.py
# ==========================
import discord
from discord.ext import commands
import time
from core import db


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── Quand le bot est prêt ───────────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        print(f"[INFO] {self.bot.user} connecté ✅")
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
        """Vérifie les stickies et relance la détection de commandes."""
        if message.author.bot:
            return  # ignorer les bots

        guild_id = message.guild.id
        channel_id = message.channel.id

        # Vérifier si un sticky est défini pour ce salon
        sticky = await db.get_sticky(guild_id, channel_id)
        if sticky:
            sticky_id, content, author_id = sticky

            try:
                old_msg = await message.channel.fetch_message(sticky_id)
                await old_msg.delete()
            except Exception:
                pass  # si l'ancien sticky n'existe plus, on ignore

            # Reposter le sticky
            new_sticky = await message.channel.send(content)

            # Mettre à jour en DB
            await db.set_sticky(guild_id, channel_id, new_sticky.id, content, author_id)

        # 🔥 LIGNE CRUCIALE : permet de traiter les commandes (*help, *join, etc.)
        await self.bot.process_commands(message)

    # ─── Gestion des erreurs de commandes ─────────────────────────────
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):

            # ─── Cas : rôles Pomodoro manquants ─────────────────────────
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

                    # Annulation
                    if str(reaction.emoji) == "❌":
                        await ctx.send("❌ Création des rôles annulée.")
                        return

                    # Création avec noms par défaut
                    if str(reaction.emoji) == "✅":
                        role_a = await ctx.guild.create_role(name="50-10")
                        role_b = await ctx.guild.create_role(name="25-5")
                        await db.set_setting("pomodoro_role_A", str(role_a.id))
                        await db.set_setting("pomodoro_role_B", str(role_b.id))
                        await ctx.send("✅ Rôles créés et enregistrés avec succès !")
                        return

                    # Personnalisation des noms
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

            # ─── Cas : salon Pomodoro manquant ───────────────────────────
            elif str(error) == "NO_POMODORO_CHANNEL":
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


async def setup(bot):
    await bot.add_cog(Events(bot))
