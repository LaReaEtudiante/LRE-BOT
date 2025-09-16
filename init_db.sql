-- ==========================
-- LRE-BOT/init_db.sql
-- ==========================

-- ---- CONFIG BOT ----
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---- USERS ----
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    join_date INTEGER,
    leave_date INTEGER,
    total_time INTEGER DEFAULT 0,
    total_A INTEGER DEFAULT 0,
    total_B INTEGER DEFAULT 0,
    pause_A INTEGER DEFAULT 0,
    pause_B INTEGER DEFAULT 0,
    sessions_count INTEGER DEFAULT 0,
    streak_current INTEGER DEFAULT 0,
    streak_best INTEGER DEFAULT 0,
    first_session INTEGER,
    last_session INTEGER,
    missed_validations INTEGER DEFAULT 0
);

-- ---- PARTICIPANTS ----
CREATE TABLE IF NOT EXISTS participants (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    join_ts INTEGER NOT NULL,
    mode TEXT NOT NULL,
    validated INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

-- ---- SESSION LOGS ----
CREATE TABLE IF NOT EXISTS session_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    mode TEXT NOT NULL,
    start_ts INTEGER NOT NULL,
    end_ts INTEGER,
    validated INTEGER DEFAULT 0
);

-- ---- STICKIES ----
CREATE TABLE IF NOT EXISTS stickies (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    author_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

-- ---- PRESENCE CHECKS ----
CREATE TABLE IF NOT EXISTS presence_checks (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    deadline_ts INTEGER NOT NULL,
    validated INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, session_id)
);
