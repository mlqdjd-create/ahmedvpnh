import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from config import OWNER_ID
import psycopg
from psycopg.rows import dict_row
# ==================== DATABASE CONNECTION ====================

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # ✅ استخدام PostgreSQL (Supabase)
    import psycopg2
    import psycopg2.extras
    DB_TYPE = "postgres"
    print("[DB] ✅ Using PostgreSQL (Supabase)")
else:
    # ⚠️ Fallback محلي (SQLite)
    import sqlite3
    from config import DB_FILE
    DB_TYPE = "sqlite"
    print("[DB] ⚠️ Using local SQLite (data will be lost on redeploy)")

# Placeholder حسب نوع قاعدة البيانات
PH = "%s" if DB_TYPE == "postgres" else "?"


def get_connection():
    if DB_TYPE == "postgres":
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        conn = sqlite3.connect(str(DB_FILE), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn


def _fetch_all(cursor):
    """يحوّل النتائج إلى قائمة dicts بغض النظر عن نوع DB"""
    if DB_TYPE == "postgres":
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    else:
        return [dict(row) for row in cursor.fetchall()]


def _fetch_one(cursor):
    """يحوّل النتيجة إلى dict واحد"""
    if DB_TYPE == "postgres":
        row = cursor.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, row))
    else:
        row = cursor.fetchone()
        return dict(row) if row else None


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Servers table
    if DB_TYPE == "postgres":
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            protocol TEXT NOT NULL,
            config TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            telegram_id BIGINT PRIMARY KEY,
            username TEXT,
            added_by BIGINT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            client_ip TEXT,
            app_version TEXT,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        # SQLite
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            protocol TEXT NOT NULL,
            config TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            added_by INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            client_ip TEXT,
            app_version TEXT,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()
    conn.close()
    print(f"[DB] ✅ Tables initialized ({DB_TYPE})")


# ==================== SERVERS CRUD ====================

def add_server(name: str, protocol: str, config: str) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    if DB_TYPE == "postgres":
        cursor.execute(
            f"INSERT INTO servers (name, protocol, config) VALUES ({PH}, {PH}, {PH}) RETURNING id",
            (name.strip(), protocol.strip().upper(), config.strip())
        )
        new_id = cursor.fetchone()[0]
    else:
        cursor.execute(
            f"INSERT INTO servers (name, protocol, config) VALUES ({PH}, {PH}, {PH})",
            (name.strip(), protocol.strip().upper(), config.strip())
        )
        new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id


def get_all_servers() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, protocol, config, created_at FROM servers ORDER BY id DESC")
    result = _fetch_all(cursor)
    conn.close()
    return result


def get_server_by_id(server_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT id, name, protocol, config, created_at FROM servers WHERE id = {PH}",
        (server_id,)
    )
    result = _fetch_one(cursor)
    conn.close()
    return result


def delete_server(server_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM servers WHERE id = {PH}", (server_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def get_servers_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM servers")
    row = cursor.fetchone()
    count = row[0] if DB_TYPE == "postgres" else row["count"]
    conn.close()
    return count


# ==================== ADMINS MANAGEMENT ====================

def add_admin(telegram_id: int, username: Optional[str] = None, added_by: Optional[int] = None) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        if DB_TYPE == "postgres":
            cursor.execute(f"""
            INSERT INTO admins (telegram_id, username, added_by, added_at)
            VALUES ({PH}, {PH}, {PH}, CURRENT_TIMESTAMP)
            ON CONFLICT (telegram_id) DO UPDATE SET
                username = EXCLUDED.username,
                added_by = EXCLUDED.added_by,
                added_at = CURRENT_TIMESTAMP
            """, (telegram_id, username or "", added_by))
        else:
            cursor.execute(f"""
            INSERT OR REPLACE INTO admins (telegram_id, username, added_by, added_at)
            VALUES ({PH}, {PH}, {PH}, CURRENT_TIMESTAMP)
            """, (telegram_id, username or "", added_by))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] add_admin error: {e}")
        return False


def remove_admin(telegram_id: int) -> bool:
    if telegram_id == OWNER_ID:
        return False
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM admins WHERE telegram_id = {PH}", (telegram_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def is_admin(telegram_id: int) -> bool:
    if telegram_id == OWNER_ID:
        return True
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT 1 FROM admins WHERE telegram_id = {PH}", (telegram_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def get_all_admins() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id, username, added_by, added_at FROM admins ORDER BY added_at DESC")
    result = _fetch_all(cursor)
    conn.close()
    return result


def get_admins_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM admins")
    row = cursor.fetchone()
    db_count = row[0] if DB_TYPE == "postgres" else row["count"]
    cursor.execute(f"SELECT 1 FROM admins WHERE telegram_id = {PH}", (OWNER_ID,))
    has_owner = cursor.fetchone() is not None
    conn.close()
    return db_count if has_owner else db_count + 1


# ==================== APP USERS TRACKING ====================

def register_or_update_user(user_id: str, client_ip: str = "", app_version: str = "") -> bool:
    if not user_id or not user_id.strip():
        return False
    user_id = user_id.strip()
    try:
        conn = get_connection()
        cursor = conn.cursor()
        if DB_TYPE == "postgres":
            cursor.execute(f"""
            INSERT INTO users (user_id, client_ip, app_version, last_seen, created_at)
            VALUES ({PH}, {PH}, {PH}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                client_ip = EXCLUDED.client_ip,
                app_version = EXCLUDED.app_version,
                last_seen = CURRENT_TIMESTAMP
            """, (user_id, client_ip, app_version))
        else:
            cursor.execute(f"""
            INSERT INTO users (user_id, client_ip, app_version, last_seen, created_at)
            VALUES ({PH}, {PH}, {PH}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                client_ip = excluded.client_ip,
                app_version = excluded.app_version,
                last_seen = CURRENT_TIMESTAMP
            """, (user_id, client_ip, app_version))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] register_user error: {e}")
        return False


def get_users_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM users")
    row = cursor.fetchone()
    count = row[0] if DB_TYPE == "postgres" else row["count"]
    conn.close()
    return count


def get_all_users(limit: int = 100) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT user_id, client_ip, app_version, last_seen, created_at FROM users ORDER BY last_seen DESC LIMIT {PH}",
        (limit,)
    )
    result = _fetch_all(cursor)
    conn.close()
    return result


def get_system_stats() -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    row = cursor.fetchone()
    total_users = row[0] if DB_TYPE == "postgres" else row["c"]

    cursor.execute("SELECT COUNT(*) FROM servers")
    row = cursor.fetchone()
    total_servers = row[0] if DB_TYPE == "postgres" else row["c"]

    cursor.execute("SELECT COUNT(*) FROM admins")
    row = cursor.fetchone()
    admin_count = row[0] if DB_TYPE == "postgres" else row["c"]

    cursor.execute(f"SELECT 1 FROM admins WHERE telegram_id = {PH}", (OWNER_ID,))
    if not cursor.fetchone():
        admin_count += 1

    conn.close()

    return {
        "total_users": total_users,
        "total_servers": total_servers,
        "total_admins": admin_count,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "api_status": "Online 🟢"
    }


# Initialize tables immediately on import
init_db()
