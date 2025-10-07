# ==========================
# LRE-BOT/src/main.py
# ==========================
import discord
from discord.ext import commands
from pathlib import Path
from core import config

# ─── Vérifications & préparation du dossier DB ──────────────
Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# ─── Intents Discord ─────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # nécessaire pour lire les commandes des utilisateurs

# ─── Création du bot ─────────────────────────────────────────
bot = commands.Bot(command_prefix="*", help_command=None, intents=intents)

# ─── Chargement automatique des Cogs ─────────────────────────
async def _setup_hook():
    initial_cogs = ["cogs.admin", "cogs.user", "cogs.pomodoro", "cogs.events"]

    for cog in initial_cogs:
        try:
            await bot.load_extension(cog)
            print(f"[COG] ✅ {cog} chargé")
        except Exception as e:
            print(f"[COG] ❌ Erreur lors du chargement de {cog} : {e}")

    print("[INFO] Tous les Cogs ont été traités.")

bot.setup_hook = _setup_hook  # <-- important pour discord.py 2.x+

# ─── Vérification du token ───────────────────────────────────
if not config.TOKEN:
    raise ValueError("❌ Le token Discord est introuvable. Vérifie ton fichier .env !")

# ─── Lancement du bot ────────────────────────────────────────
if __name__ == "__main__":
    print("[INFO] Démarrage du bot LRE...")
    bot.run(config.TOKEN)
