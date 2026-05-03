# ==========================
# LRE-BOT/src/core/db.py
# ==========================
import aiosqlite
import time
from pathlib import Path
from datetime import datetime, timedelta
from . import config
import logging

logger = logging.getLogger('LRE-BOT.db')

DB_PATH = config.DB_PATH

def now_ts():
    """Retourne le timestamp actuel (entier)"""
    return int(time.time())


async def init_db():
    """Initialise la base de données avec toutes les tables"""
    async with aiosqlite.connect(DB_PATH) as conn:
        # --- VERIFICATION MIGRATION ---
        async with conn.execute("PRAGMA table_info(users)") as cursor:
            columns = await cursor.fetchall()
        
        column_names = [col[1] for col in columns]
        needs_migration = bool(column_names and "guild_id" not in column_names)

        if needs_migration:
            logger.info("⏳ Migration de la table 'users' vers le nouveau format...")
            await conn.execute("ALTER TABLE users RENAME TO users_old")
            
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

        if needs_migration:
            await conn.execute("""
                INSERT INTO users (
                    user_id, guild_id, username, join_date, leave_date,
                    total_time, total_A, total_B, pause_time_A, pause_time_B,
                    sessions_count, streak_current, streak_best,
                    first_session, last_session_date
                )
                SELECT 
                    user_id, 0, username, join_date, leave_date,
                    total_time, total_A, total_B, pause_A, pause_B,
                    sessions_count, streak_current, streak_best,
                    first_session, last_session
                FROM users_old
            """)
            await conn.execute("DROP TABLE users_old")

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
                join_ts INTEGER NOT NULL,
                mode TEXT NOT NULL,
                validated INTEGER DEFAULT 0,
                cycles_completed INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        # Migration pour ajouter cycles_completed sur base existante
        try:
            await conn.execute("ALTER TABLE participants ADD COLUMN cycles_completed INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass

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
        logger.info("✅ Base de données SQLite initialisée et synchronisée avec succès.")


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


async def get_user_stats(user_id: int, guild_id: int):
    """Récupérer les infos étendues d'un utilisateur, incluant les rangs"""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        
        async with conn.execute("""
            SELECT *,
                (total_time + pause_time_A + pause_time_B) as temps_total_global,
                (pause_time_A + pause_time_B) as temps_repos
            FROM users WHERE user_id = ? AND guild_id = ?
        """, (user_id, guild_id)) as cursor:
            user = await cursor.fetchone()
            
        if not user:
            return None
            
        user_data = dict(user)
        
        # Rangs personnels
        async with conn.execute("SELECT COUNT(*) FROM users WHERE guild_id = ? AND total_time > ?", (guild_id, user_data['total_time'])) as cursor:
            user_data['rank_work'] = (await cursor.fetchone())[0] + 1
            
        async with conn.execute("SELECT COUNT(*) FROM users WHERE guild_id = ? AND (total_time + pause_time_A + pause_time_B) > ?", (guild_id, user_data['temps_total_global'])) as cursor:
            user_data['rank_total'] = (await cursor.fetchone())[0] + 1
            
        async with conn.execute("SELECT COUNT(*) FROM users WHERE guild_id = ? AND (pause_time_A + pause_time_B) > ?", (guild_id, user_data['temps_repos'])) as cursor:
            user_data['rank_rest'] = (await cursor.fetchone())[0] + 1
            
        async with conn.execute("SELECT COUNT(*) FROM users WHERE guild_id = ? AND streak_best > ?", (guild_id, user_data['streak_best'])) as cursor:
            user_data['rank_streak'] = (await cursor.fetchone())[0] + 1

        return user_data


async def add_participant(guild_id: int, user_id: int, mode: str):
    """Ajouter un participant à une session"""
    async with aiosqlite.connect(DB_PATH) as conn:
        try:
            await conn.execute("""
                INSERT INTO participants (guild_id, user_id, join_ts, mode)
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
            SELECT join_ts, mode FROM participants
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
            SELECT join_ts, mode FROM participants
            WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id)) as cursor:
            return await cursor.fetchone()


async def update_participant_state(guild_id: int, user_id: int, validated: int = None, increment_cycles: bool = False):
    """Met à jour l'état de validation et/ou incrémente les cycles complétés d'un participant"""
    async with aiosqlite.connect(DB_PATH) as conn:
        if validated is not None and increment_cycles:
            await conn.execute("""
                UPDATE participants 
                SET validated = ?, cycles_completed = cycles_completed + 1
                WHERE guild_id = ? AND user_id = ?
            """, (validated, guild_id, user_id))
        elif validated is not None:
            await conn.execute("""
                UPDATE participants 
                SET validated = ?
                WHERE guild_id = ? AND user_id = ?
            """, (validated, guild_id, user_id))
        elif increment_cycles:
            await conn.execute("""
                UPDATE participants 
                SET cycles_completed = cycles_completed + 1
                WHERE guild_id = ? AND user_id = ?
            """, (guild_id, user_id))
        await conn.commit()


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
    """Récupérer les statistiques globales et calendaires du serveur"""
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

        now = datetime.now()
        start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ts_week = int(start_of_week.timestamp())
        ts_month = int(start_of_month.timestamp())

        async with conn.execute("SELECT COUNT(DISTINCT user_id) FROM sessions WHERE guild_id = ? AND start_timestamp >= ?", (guild_id, ts_week)) as cursor:
            unique_users_week = (await cursor.fetchone())[0]
            
        async with conn.execute("SELECT COUNT(DISTINCT user_id) FROM sessions WHERE guild_id = ? AND start_timestamp >= ?", (guild_id, ts_month)) as cursor:
            unique_users_month = (await cursor.fetchone())[0]
            
        async with conn.execute("SELECT COUNT(*) FROM sessions WHERE guild_id = ? AND start_timestamp >= ?", (guild_id, ts_week)) as cursor:
            sessions_week = (await cursor.fetchone())[0]
            
        async with conn.execute("SELECT COUNT(*) FROM sessions WHERE guild_id = ? AND start_timestamp >= ?", (guild_id, ts_month)) as cursor:
            sessions_month = (await cursor.fetchone())[0]
            
        async with conn.execute("SELECT COUNT(*) FROM sessions WHERE guild_id = ?", (guild_id,)) as cursor:
            total_sessions = (await cursor.fetchone())[0]

        return {
            "users": stats[0],
            "total_time": stats[1],
            "avg_time": int(stats[2]),
            "unique_users_week": unique_users_week,
            "unique_users_month": unique_users_month,
            "sessions_week": sessions_week,
            "sessions_month": sessions_month,
            "total_sessions": total_sessions
        }


async def get_leaderboards(guild_id: int):
    """Récupérer les classements étendus"""
    now = datetime.now()
    start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ts_week = int(start_of_week.timestamp())
    ts_month = int(start_of_month.timestamp())

    async with aiosqlite.connect(DB_PATH) as conn:
        # Top temps global (travail + repos)
        async with conn.execute("""
            SELECT user_id, (total_time + pause_time_A + pause_time_B) as total_global 
            FROM users 
            WHERE guild_id = ? AND (total_time + pause_time_A + pause_time_B) > 0
            ORDER BY total_global DESC LIMIT 10
        """, (guild_id,)) as cursor:
            top_global = await cursor.fetchall()

        # Top temps travail
        async with conn.execute("""
            SELECT user_id, total_time FROM users 
            WHERE guild_id = ? AND total_time > 0
            ORDER BY total_time DESC LIMIT 10
        """, (guild_id,)) as cursor:
            top_work = await cursor.fetchall()
            
        # Top repos (Le flemmard)
        async with conn.execute("""
            SELECT user_id, (pause_time_A + pause_time_B) as repos 
            FROM users 
            WHERE guild_id = ? AND (pause_time_A + pause_time_B) > 0
            ORDER BY repos DESC LIMIT 10
        """, (guild_id,)) as cursor:
            top_rest = await cursor.fetchall()

        # Top semaine calendaire
        async with conn.execute("""
            SELECT user_id, SUM(work_time) as work_week 
            FROM sessions 
            WHERE guild_id = ? AND start_timestamp >= ? 
            GROUP BY user_id 
            ORDER BY work_week DESC LIMIT 10
        """, (guild_id, ts_week)) as cursor:
            top_week = await cursor.fetchall()

        # Top mois calendaire
        async with conn.execute("""
            SELECT user_id, SUM(work_time) as work_month
            FROM sessions 
            WHERE guild_id = ? AND start_timestamp >= ? 
            GROUP BY user_id 
            ORDER BY work_month DESC LIMIT 10
        """, (guild_id, ts_month)) as cursor:
            top_month = await cursor.fetchall()

        # Top streaks
        async with conn.execute("""
            SELECT user_id, streak_current, streak_best FROM users 
            WHERE guild_id = ? AND streak_best > 0
            ORDER BY streak_best DESC LIMIT 10
        """, (guild_id,)) as cursor:
            top_streak = await cursor.fetchall()

        return {
            "🌎 Temps Total (Travail + Repos)": top_global,
            "⏱️ Meilleur Temps de Travail": top_work,
            "🛌 Le Flemmard (Meilleur Repos)": top_rest,
            "📅 Temps de Travail (Cette Semaine)": top_week,
            "📆 Temps de Travail (Ce Mois)": top_month,
            "🔥 Meilleurs Streaks": top_streak
        }

async def get_yearly_analytics(guild_id: int, year: int):
    """Récupère les statistiques agrégées par mois pour une année spécifique."""
    dt_start = datetime(year, 1, 1)
    dt_end = datetime(year + 1, 1, 1) if year < 9999 else datetime(year, 12, 31, 23, 59, 59)
    ts_start = int(dt_start.timestamp())
    ts_end = int(dt_end.timestamp())
    
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("""
            SELECT 
                CAST(strftime('%m', datetime(start_timestamp, 'unixepoch', 'localtime')) AS INTEGER) as month,
                COUNT(DISTINCT user_id) as unique_users,
                COUNT(*) as total_sessions,
                SUM(work_time) as total_work,
                SUM(pause_time) as total_pause
            FROM sessions
            WHERE guild_id = ? AND start_timestamp >= ? AND start_timestamp < ?
            GROUP BY month
            ORDER BY month ASC
        """, (guild_id, ts_start, ts_end)) as cursor:
            rows = await cursor.fetchall()
            
    analytics = {m: {"users": 0, "sessions": 0, "work": 0, "pause": 0} for m in range(1, 13)}
    for row in rows:
        month = row[0]
        if month in analytics:
            analytics[month] = {
                "users": row[1],
                "sessions": row[2],
                "work": row[3] or 0,
                "pause": row[4] or 0
            }
    return analytics


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
# ==========================
# LRE-BOT/src/core/db.py
# ==========================
import aiosqlite
import time
from pathlib import Path
from datetime import datetime, timedelta
from . import config
import logging

logger = logging.getLogger('LRE-BOT.db')

DB_PATH = config.DB_PATH

def now_ts():
    """Retourne le timestamp actuel (entier)"""
    return int(time.time())


async def init_db():
    """Initialise la base de données avec toutes les tables"""
    async with aiosqlite.connect(DB_PATH) as conn:
        # --- VERIFICATION MIGRATION ---
        async with conn.execute("PRAGMA table_info(users)") as cursor:
            columns = await cursor.fetchall()
        
        column_names = [col[1] for col in columns]
        needs_migration = bool(column_names and "guild_id" not in column_names)

        if needs_migration:
            logger.info("⏳ Migration de la table 'users' vers le nouveau format...")
            await conn.execute("ALTER TABLE users RENAME TO users_old")
            
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

        if needs_migration:
            await conn.execute("""
                INSERT INTO users (
                    user_id, guild_id, username, join_date, leave_date,
                    total_time, total_A, total_B, pause_time_A, pause_time_B,
                    sessions_count, streak_current, streak_best,
                    first_session, last_session_date
                )
                SELECT 
                    user_id, 0, username, join_date, leave_date,
                    total_time, total_A, total_B, pause_A, pause_B,
                    sessions_count, streak_current, streak_best,
                    first_session, last_session
                FROM users_old
            """)
            await conn.execute("DROP TABLE users_old")

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
                join_ts INTEGER NOT NULL,
                mode TEXT NOT NULL,
                validated INTEGER DEFAULT 0,
                cycles_completed INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        # Migration pour ajouter cycles_completed sur base existante
        try:
            await conn.execute("ALTER TABLE participants ADD COLUMN cycles_completed INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass

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
        logger.info("✅ Base de données SQLite initialisée et synchronisée avec succès.")


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


async def get_user_stats(user_id: int, guild_id: int):
    """Récupérer les infos étendues d'un utilisateur, incluant les rangs"""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        
        async with conn.execute("""
            SELECT *,
                (total_time + pause_time_A + pause_time_B) as temps_total_global,
                (pause_time_A + pause_time_B) as temps_repos
            FROM users WHERE user_id = ? AND guild_id = ?
        """, (user_id, guild_id)) as cursor:
            user = await cursor.fetchone()
            
        if not user:
            return None
            
        user_data = dict(user)
        
        # Rangs personnels
        async with conn.execute("SELECT COUNT(*) FROM users WHERE guild_id = ? AND total_time > ?", (guild_id, user_data['total_time'])) as cursor:
            user_data['rank_work'] = (await cursor.fetchone())[0] + 1
            
        async with conn.execute("SELECT COUNT(*) FROM users WHERE guild_id = ? AND (total_time + pause_time_A + pause_time_B) > ?", (guild_id, user_data['temps_total_global'])) as cursor:
            user_data['rank_total'] = (await cursor.fetchone())[0] + 1
            
        async with conn.execute("SELECT COUNT(*) FROM users WHERE guild_id = ? AND (pause_time_A + pause_time_B) > ?", (guild_id, user_data['temps_repos'])) as cursor:
            user_data['rank_rest'] = (await cursor.fetchone())[0] + 1
            
        async with conn.execute("SELECT COUNT(*) FROM users WHERE guild_id = ? AND streak_best > ?", (guild_id, user_data['streak_best'])) as cursor:
            user_data['rank_streak'] = (await cursor.fetchone())[0] + 1

        return user_data


async def add_participant(guild_id: int, user_id: int, mode: str):
    """Ajouter un participant à une session"""
    async with aiosqlite.connect(DB_PATH) as conn:
        try:
            await conn.execute("""
                INSERT INTO participants (guild_id, user_id, join_ts, mode)
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
            SELECT join_ts, mode FROM participants
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
            SELECT join_ts, mode FROM participants
            WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id)) as cursor:
            return await cursor.fetchone()


async def update_participant_state(guild_id: int, user_id: int, validated: int = None, increment_cycles: bool = False):
    """Met à jour l'état de validation et/ou incrémente les cycles complétés d'un participant"""
    async with aiosqlite.connect(DB_PATH) as conn:
        if validated is not None and increment_cycles:
            await conn.execute("""
                UPDATE participants 
                SET validated = ?, cycles_completed = cycles_completed + 1
                WHERE guild_id = ? AND user_id = ?
            """, (validated, guild_id, user_id))
        elif validated is not None:
            await conn.execute("""
                UPDATE participants 
                SET validated = ?
                WHERE guild_id = ? AND user_id = ?
            """, (validated, guild_id, user_id))
        elif increment_cycles:
            await conn.execute("""
                UPDATE participants 
                SET cycles_completed = cycles_completed + 1
                WHERE guild_id = ? AND user_id = ?
            """, (guild_id, user_id))
        await conn.commit()


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
    """Récupérer les statistiques globales et calendaires du serveur"""
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

        now = datetime.now()
        start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ts_week = int(start_of_week.timestamp())
        ts_month = int(start_of_month.timestamp())

        async with conn.execute("SELECT COUNT(DISTINCT user_id) FROM sessions WHERE guild_id = ? AND start_timestamp >= ?", (guild_id, ts_week)) as cursor:
            unique_users_week = (await cursor.fetchone())[0]
            
        async with conn.execute("SELECT COUNT(DISTINCT user_id) FROM sessions WHERE guild_id = ? AND start_timestamp >= ?", (guild_id, ts_month)) as cursor:
            unique_users_month = (await cursor.fetchone())[0]
            
        async with conn.execute("SELECT COUNT(*) FROM sessions WHERE guild_id = ? AND start_timestamp >= ?", (guild_id, ts_week)) as cursor:
            sessions_week = (await cursor.fetchone())[0]
            
        async with conn.execute("SELECT COUNT(*) FROM sessions WHERE guild_id = ? AND start_timestamp >= ?", (guild_id, ts_month)) as cursor:
            sessions_month = (await cursor.fetchone())[0]
            
        async with conn.execute("SELECT COUNT(*) FROM sessions WHERE guild_id = ?", (guild_id,)) as cursor:
            total_sessions = (await cursor.fetchone())[0]

        return {
            "users": stats[0],
            "total_time": stats[1],
            "avg_time": int(stats[2]),
            "unique_users_week": unique_users_week,
            "unique_users_month": unique_users_month,
            "sessions_week": sessions_week,
            "sessions_month": sessions_month,
            "total_sessions": total_sessions
        }


async def get_leaderboards(guild_id: int):
    """Récupérer les classements étendus"""
    now = datetime.now()
    start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ts_week = int(start_of_week.timestamp())
    ts_month = int(start_of_month.timestamp())

    async with aiosqlite.connect(DB_PATH) as conn:
        # Top temps global (travail + repos)
        async with conn.execute("""
            SELECT user_id, (total_time + pause_time_A + pause_time_B) as total_global 
            FROM users 
            WHERE guild_id = ? AND (total_time + pause_time_A + pause_time_B) > 0
            ORDER BY total_global DESC LIMIT 10
        """, (guild_id,)) as cursor:
            top_global = await cursor.fetchall()

        # Top temps travail
        async with conn.execute("""
            SELECT user_id, total_time FROM users 
            WHERE guild_id = ? AND total_time > 0
            ORDER BY total_time DESC LIMIT 10
        """, (guild_id,)) as cursor:
            top_work = await cursor.fetchall()
            
        # Top repos (Le flemmard)
        async with conn.execute("""
            SELECT user_id, (pause_time_A + pause_time_B) as repos 
            FROM users 
            WHERE guild_id = ? AND (pause_time_A + pause_time_B) > 0
            ORDER BY repos DESC LIMIT 10
        """, (guild_id,)) as cursor:
            top_rest = await cursor.fetchall()

        # Top semaine calendaire
        async with conn.execute("""
            SELECT user_id, SUM(work_time) as work_week 
            FROM sessions 
            WHERE guild_id = ? AND start_timestamp >= ? 
            GROUP BY user_id 
            ORDER BY work_week DESC LIMIT 10
        """, (guild_id, ts_week)) as cursor:
            top_week = await cursor.fetchall()

        # Top mois calendaire
        async with conn.execute("""
            SELECT user_id, SUM(work_time) as work_month
            FROM sessions 
            WHERE guild_id = ? AND start_timestamp >= ? 
            GROUP BY user_id 
            ORDER BY work_month DESC LIMIT 10
        """, (guild_id, ts_month)) as cursor:
            top_month = await cursor.fetchall()

        # Top streaks
        async with conn.execute("""
            SELECT user_id, streak_current, streak_best FROM users 
            WHERE guild_id = ? AND streak_best > 0
            ORDER BY streak_best DESC LIMIT 10
        """, (guild_id,)) as cursor:
            top_streak = await cursor.fetchall()

        return {
            "🌎 Temps Total (Travail + Repos)": top_global,
            "⏱️ Meilleur Temps de Travail": top_work,
            "🛌 Le Flemmard (Meilleur Repos)": top_rest,
            "📅 Temps de Travail (Cette Semaine)": top_week,
            "📆 Temps de Travail (Ce Mois)": top_month,
            "🔥 Meilleurs Streaks": top_streak
        }

async def get_yearly_analytics(guild_id: int, year: int):
    """Récupère les statistiques agrégées par mois pour une année spécifique."""
    dt_start = datetime(year, 1, 1)
    dt_end = datetime(year + 1, 1, 1) if year < 9999 else datetime(year, 12, 31, 23, 59, 59)
    ts_start = int(dt_start.timestamp())
    ts_end = int(dt_end.timestamp())
    
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("""
            SELECT 
                CAST(strftime('%m', datetime(start_timestamp, 'unixepoch', 'localtime')) AS INTEGER) as month,
                COUNT(DISTINCT user_id) as unique_users,
                COUNT(*) as total_sessions,
                SUM(work_time) as total_work,
                SUM(pause_time) as total_pause
            FROM sessions
            WHERE guild_id = ? AND start_timestamp >= ? AND start_timestamp < ?
            GROUP BY month
            ORDER BY month ASC
        """, (guild_id, ts_start, ts_end)) as cursor:
            rows = await cursor.fetchall()
            
    analytics = {m: {"users": 0, "sessions": 0, "work": 0, "pause": 0} for m in range(1, 13)}
    for row in rows:
        month = row[0]
        if month in analytics:
            analytics[month] = {
                "users": row[1],
                "sessions": row[2],
                "work": row[3] or 0,
                "pause": row[4] or 0
            }
    return analytics


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
# ==========================
# LRE-BOT/src/core/db.py
# ==========================
import aiosqlite
import time
from pathlib import Path
from datetime import datetime, timedelta
from . import config
import logging

logger = logging.getLogger('LRE-BOT.db')

DB_PATH = config.DB_PATH

def now_ts():
    """Retourne le timestamp actuel (entier)"""
    return int(time.time())


async def init_db():
    """Initialise la base de données avec toutes les tables"""
    async with aiosqlite.connect(DB_PATH) as conn:
        # --- VERIFICATION MIGRATION ---
        async with conn.execute("PRAGMA table_info(users)") as cursor:
            columns = await cursor.fetchall()
        
        column_names = [col[1] for col in columns]
        needs_migration = bool(column_names and "guild_id" not in column_names)

        if needs_migration:
            logger.info("⏳ Migration de la table 'users' vers le nouveau format...")
            await conn.execute("ALTER TABLE users RENAME TO users_old")
            
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

        if needs_migration:
            await conn.execute("""
                INSERT INTO users (
                    user_id, guild_id, username, join_date, leave_date,
                    total_time, total_A, total_B, pause_time_A, pause_time_B,
                    sessions_count, streak_current, streak_best,
                    first_session, last_session_date
                )
                SELECT 
                    user_id, 0, username, join_date, leave_date,
                    total_time, total_A, total_B, pause_A, pause_B,
                    sessions_count, streak_current, streak_best,
                    first_session, last_session
                FROM users_old
            """)
            await conn.execute("DROP TABLE users_old")

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
                join_ts INTEGER NOT NULL,
                mode TEXT NOT NULL,
                validated INTEGER DEFAULT 0,
                cycles_completed INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        # Migration pour ajouter cycles_completed sur base existante
        try:
            await conn.execute("ALTER TABLE participants ADD COLUMN cycles_completed INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass

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
        logger.info("✅ Base de données SQLite initialisée et synchronisée avec succès.")


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
                INSERT INTO participants (guild_id, user_id, join_ts, mode)
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
            SELECT join_ts, mode FROM participants
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
            SELECT join_ts, mode FROM participants
            WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id)) as cursor:
            return await cursor.fetchone()


async def update_participant_state(guild_id: int, user_id: int, validated: int = None, increment_cycles: bool = False):
    """Met à jour l'état de validation et/ou incrémente les cycles complétés d'un participant"""
    async with aiosqlite.connect(DB_PATH) as conn:
        if validated is not None and increment_cycles:
            await conn.execute("""
                UPDATE participants 
                SET validated = ?, cycles_completed = cycles_completed + 1
                WHERE guild_id = ? AND user_id = ?
            """, (validated, guild_id, user_id))
        elif validated is not None:
            await conn.execute("""
                UPDATE participants 
                SET validated = ?
                WHERE guild_id = ? AND user_id = ?
            """, (validated, guild_id, user_id))
        elif increment_cycles:
            await conn.execute("""
                UPDATE participants 
                SET cycles_completed = cycles_completed + 1
                WHERE guild_id = ? AND user_id = ?
            """, (guild_id, user_id))
        await conn.commit()


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
