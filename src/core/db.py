# ==========================
# LRE-BOT/src/core/db.py
# ==========================
import aiosqlite
import time
from pathlib import Path
from datetime import datetime, timedelta
from . import config

DB_PATH = config.DB_PATH

def now_ts():
    """Retourne le timestamp actuel (entier)"""
    return int(time.time())


async def init_db():
    """Initialise la base de données avec toutes les tables"""
    async with aiosqlite.connect(DB_PATH) as conn:
        # Table users (existante avec nouvelles colonnes)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                username TEXT,
                join_date INTEGER,
                leave_date INTEGER,
                total_time INTEGER DEFAULT 0,
                total_A INTEGER DEFAULT 0,
                total_B INTEGER DEFAULT 0,
                sessions_count INTEGER DEFAULT 0,
                streak_current INTEGER DEFAULT 0,
                streak_best INTEGER DEFAULT 0,
                last_active_date INTEGER,
                first_session INTEGER,
                first_session_date INTEGER,
                last_session_date INTEGER,
                pause_time_A INTEGER DEFAULT 0,
                pause_time_B INTEGER DEFAULT 0,
                longest_session INTEGER DEFAULT 0,
                best_week_number INTEGER,
                best_week_time INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            )
        """)

        # Table sessions (nouvelle)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ('A', 'B')),
                work_time INTEGER NOT NULL,
                pause_time INTEGER NOT NULL,
                start_timestamp INTEGER NOT NULL,
                end_timestamp INTEGER NOT NULL,
                day_of_week INTEGER NOT NULL CHECK(day_of_week BETWEEN 0 AND 6),
                hour_of_day INTEGER NOT NULL CHECK(hour_of_day BETWEEN 0 AND 23)
            )
        """)

        # Table participants (existante)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                join_timestamp INTEGER NOT NULL,
                mode TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        # Table sticky_messages (existante)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sticky_messages (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                author_id INTEGER,
                PRIMARY KEY (guild_id, channel_id)
            )
        """)

        # Table maintenance (existante)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS maintenance (
                guild_id INTEGER PRIMARY KEY,
                is_active INTEGER DEFAULT 0
            )
        """)

        # Index pour optimiser les requêtes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, guild_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_timestamp ON sessions(start_timestamp)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_day ON sessions(day_of_week)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_hour ON sessions(hour_of_day)")

        await conn.commit()


async def upsert_user(user_id: int, username: str, join_date: int, guild_id: int = 0):
    """Créer ou mettre à jour un utilisateur"""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            INSERT INTO users (user_id, guild_id, username, join_date)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET
                username = excluded.username
        """, (user_id, guild_id, username, join_date))
        await conn.commit()


async def get_user(user_id: int, guild_id: int):
    """Récupérer les infos d'un utilisateur"""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("""
            SELECT * FROM users WHERE user_id = ? AND guild_id = ?
        """, (user_id, guild_id)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def add_participant(guild_id: int, user_id: int, mode: str):
    """Ajouter un participant à une session"""
    async with aiosqlite.connect(DB_PATH) as conn:
        try:
            await conn.execute("""
                INSERT INTO participants (guild_id, user_id, join_timestamp, mode)
                VALUES (?, ?, ?, ?)
            """, (guild_id, user_id, now_ts(), mode))
            await conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_participant(guild_id: int, user_id: int):
    """Retirer un participant et retourner son temps de session"""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("""
            SELECT join_timestamp, mode FROM participants
            WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id)) as cursor:
            row = await cursor.fetchone()

        if row:
            await conn.execute("""
                DELETE FROM participants WHERE guild_id = ? AND user_id = ?
            """, (guild_id, user_id))
            await conn.commit()
            return row
        return (None, None)


async def get_active_session(guild_id: int, user_id: int):
    """Récupérer la session active d'un utilisateur"""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("""
            SELECT join_timestamp, mode FROM participants
            WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id)) as cursor:
            return await cursor.fetchone()


async def ajouter_temps(user_id: int, guild_id: int, temps_sec: int, mode: str, is_session_end: bool = False):
    """
    Ajouter du temps de travail à un utilisateur
    Si is_session_end=True, on enregistre aussi la session détaillée
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        # Récupérer les stats actuelles
        async with conn.execute("""
            SELECT total_time, total_A, total_B, sessions_count, longest_session, 
                   first_session_date, last_active_date
            FROM users WHERE user_id = ? AND guild_id = ?
        """, (user_id, guild_id)) as cursor:
            user = await cursor.fetchone()

        now = now_ts()
        
        # Calculer le nouveau total
        if user:
            total_time = user[0] + temps_sec
            total_A = user[1] + (temps_sec if mode == 'A' else 0)
            total_B = user[2] + (temps_sec if mode == 'B' else 0)
            sessions_count = user[3] + (1 if is_session_end else 0)
            longest_session = max(user[4] or 0, temps_sec) if is_session_end else user[4]
            first_session_date = user[5] or now
            last_session_date = now if is_session_end else user[6]
        else:
            total_time = temps_sec
            total_A = temps_sec if mode == 'A' else 0
            total_B = temps_sec if mode == 'B' else 0
            sessions_count = 1 if is_session_end else 0
            longest_session = temps_sec if is_session_end else 0
            first_session_date = now
            last_session_date = now if is_session_end else None

        # Mettre à jour l'utilisateur
        await conn.execute("""
            INSERT INTO users (
                user_id, guild_id, total_time, total_A, total_B, 
                sessions_count, longest_session, first_session_date, 
                last_session_date, last_active_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET
                total_time = excluded.total_time,
                total_A = excluded.total_A,
                total_B = excluded.total_B,
                sessions_count = excluded.sessions_count,
                longest_session = excluded.longest_session,
                first_session_date = COALESCE(users.first_session_date, excluded.first_session_date),
                last_session_date = excluded.last_session_date,
                last_active_date = excluded.last_active_date
        """, (user_id, guild_id, total_time, total_A, total_B, sessions_count, 
              longest_session, first_session_date, last_session_date, now))

        await conn.commit()


async def record_session(user_id: int, guild_id: int, mode: str, work_time: int, 
                        pause_time: int, start_ts: int, end_ts: int):
    """Enregistrer une session détaillée dans l'historique"""
    dt = datetime.fromtimestamp(start_ts)
    day_of_week = dt.weekday()  # 0=Lundi, 6=Dimanche
    hour_of_day = dt.hour

    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            INSERT INTO sessions (
                user_id, guild_id, mode, work_time, pause_time,
                start_timestamp, end_timestamp, day_of_week, hour_of_day
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, guild_id, mode, work_time, pause_time, 
              start_ts, end_ts, day_of_week, hour_of_day))
        
        # Mettre à jour le temps de pause
        pause_column = f"pause_time_{mode}"
        await conn.execute(f"""
            UPDATE users 
            SET {pause_column} = {pause_column} + ?
            WHERE user_id = ? AND guild_id = ?
        """, (pause_time, user_id, guild_id))
        
        await conn.commit()


async def get_server_stats(guild_id: int):
    """Récupérer les statistiques du serveur"""
    async with aiosqlite.connect(DB_PATH) as conn:
        # Stats globales
        async with conn.execute("""
            SELECT 
                COUNT(DISTINCT user_id) as users,
                COALESCE(SUM(total_time), 0) as total_time,
                COALESCE(AVG(total_time), 0) as avg_time
            FROM users WHERE guild_id = ?
        """, (guild_id,)) as cursor:
            stats = await cursor.fetchone()

        # Sessions 7 derniers jours
        seven_days_ago = now_ts() - (7 * 24 * 3600)
        async with conn.execute("""
            SELECT COUNT(*) FROM sessions 
            WHERE guild_id = ? AND end_timestamp >= ?
        """, (guild_id, seven_days_ago)) as cursor:
            last_7_days = (await cursor.fetchone())[0]

        # Sessions 4 dernières semaines
        four_weeks_ago = now_ts() - (28 * 24 * 3600)
        async with conn.execute("""
            SELECT COUNT(*) FROM sessions 
            WHERE guild_id = ? AND end_timestamp >= ?
        """, (guild_id, four_weeks_ago)) as cursor:
            last_4_weeks = (await cursor.fetchone())[0]

        return {
            "users": stats[0],
            "total_time": stats[1],
            "avg_time": int(stats[2]),
            "last_7_days": last_7_days,
            "last_4_weeks": last_4_weeks
        }


async def get_leaderboards(guild_id: int):
    """Récupérer les classements"""
    async with aiosqlite.connect(DB_PATH) as conn:
        # Top temps total
        async with conn.execute("""
            SELECT user_id, total_time FROM users 
            WHERE guild_id = ? AND total_time > 0
            ORDER BY total_time DESC LIMIT 10
        """, (guild_id,)) as cursor:
            top_time = await cursor.fetchall()

        # Top streaks
        async with conn.execute("""
            SELECT user_id, streak_current, streak_best FROM users 
            WHERE guild_id = ? AND streak_best > 0
            ORDER BY streak_best DESC LIMIT 10
        """, (guild_id,)) as cursor:
            top_streak = await cursor.fetchall()

        return {
            "⏱ Temps total": top_time,
            "🔥 Meilleurs streaks": top_streak
        }


# Fonctions sticky messages (existantes)
async def get_sticky(guild_id: int, channel_id: int):
    """Récupérer un sticky message"""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("""
            SELECT message_id, content, author_id FROM sticky_messages
            WHERE guild_id = ? AND channel_id = ?
        """, (guild_id, channel_id)) as cursor:
            return await cursor.fetchone()


async def set_sticky(guild_id: int, channel_id: int, message_id: int, content: str, author_id: int = None):
    """Définir ou mettre à jour un sticky message"""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            INSERT INTO sticky_messages (guild_id, channel_id, message_id, content, author_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                message_id = excluded.message_id,
                content = excluded.content,
                author_id = excluded.author_id
        """, (guild_id, channel_id, message_id, content, author_id))
        await conn.commit()


async def remove_sticky(guild_id: int, channel_id: int):
    """Supprimer un sticky message"""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            DELETE FROM sticky_messages 
            WHERE guild_id = ? AND channel_id = ?
        """, (guild_id, channel_id))
        await conn.commit()


# Fonctions maintenance (existantes)
async def is_maintenance_active(guild_id: int):
    """Vérifier si le mode maintenance est actif"""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("""
            SELECT is_active FROM maintenance WHERE guild_id = ?
        """, (guild_id,)) as cursor:
            row = await cursor.fetchone()
            return bool(row[0]) if row else False


async def toggle_maintenance(guild_id: int):
    """Activer/désactiver le mode maintenance"""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("""
            SELECT is_active FROM maintenance WHERE guild_id = ?
        """, (guild_id,)) as cursor:
            row = await cursor.fetchone()

        new_state = 0 if (row and row[0]) else 1

        await conn.execute("""
            INSERT INTO maintenance (guild_id, is_active) VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET is_active = excluded.is_active
        """, (guild_id, new_state))
        await conn.commit()

        return bool(new_state)
