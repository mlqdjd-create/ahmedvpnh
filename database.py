import sqlite3
from typing import List, Dict, Any, Optional
from datetime import datetime
from config import DB_FILE, OWNER_ID

def get_connection():
    conn = sqlite3.connect(str(DB_FILE), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Servers table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            protocol TEXT NOT NULL,
            config TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Admins table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            added_by INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # App registered users table
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

# ==================== SERVERS CRUD ====================

def add_server(name: str, protocol: str, config: str) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO servers (name, protocol, config)
        VALUES (?, ?, ?)
        """, (name.strip(), protocol.strip().upper(), config.strip()))
        conn.commit()
        return cursor.lastrowid

def get_all_servers() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, protocol, config, created_at FROM servers ORDER BY id DESC")
        return [dict(row) for row in cursor.fetchall()]

def get_server_by_id(server_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, protocol, config, created_at FROM servers WHERE id = ?", (server_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def delete_server(server_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM servers WHERE id = ?", (server_id,))
        conn.commit()
        return cursor.rowcount > 0

def get_servers_count() -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM servers")
        row = cursor.fetchone()
        return row["count"] if row else 0

# ==================== ADMINS MANAGEMENT ====================

def add_admin(telegram_id: int, username: Optional[str] = None, added_by: Optional[int] = None) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO admins (telegram_id, username, added_by, added_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (telegram_id, username or "", added_by))
            conn.commit()
            return True
    except Exception:
        return False

def remove_admin(telegram_id: int) -> bool:
    # Protect Primary Owner from being deleted
    if telegram_id == OWNER_ID:
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM admins WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
        return cursor.rowcount > 0

def is_admin(telegram_id: int) -> bool:
    if telegram_id == OWNER_ID:
        return True
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM admins WHERE telegram_id = ?", (telegram_id,))
        return cursor.fetchone() is not None

def get_all_admins() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_id, username, added_by, added_at FROM admins ORDER BY added_at DESC")
        return [dict(row) for row in cursor.fetchall()]

def get_admins_count() -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM admins")
        row = cursor.fetchone()
        db_count = row["count"] if row else 0
        # Include Owner if not in table
        cursor.execute("SELECT 1 FROM admins WHERE telegram_id = ?", (OWNER_ID,))
        has_owner = cursor.fetchone() is not None
        return db_count if has_owner else db_count + 1

# ==================== APP USERS TRACKING ====================

def register_or_update_user(user_id: str, client_ip: str = "", app_version: str = "") -> bool:
    if not user_id or not user_id.strip():
        return False
    user_id = user_id.strip()
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO users (user_id, client_ip, app_version, last_seen, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                client_ip = excluded.client_ip,
                app_version = excluded.app_version,
                last_seen = CURRENT_TIMESTAMP
            """, (user_id, client_ip, app_version))
            conn.commit()
            return True
    except Exception:
        return False

def get_users_count() -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM users")
        row = cursor.fetchone()
        return row["count"] if row else 0

def get_all_users(limit: int = 100) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, client_ip, app_version, last_seen, created_at FROM users ORDER BY last_seen DESC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]

def get_system_stats() -> Dict[str, Any]:
    with get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as c FROM users")
        total_users = cursor.fetchone()["c"]
        
        cursor.execute("SELECT COUNT(*) as c FROM servers")
        total_servers = cursor.fetchone()["c"]
        
        cursor.execute("SELECT COUNT(*) as c FROM admins")
        admin_count = cursor.fetchone()["c"]
        cursor.execute("SELECT 1 FROM admins WHERE telegram_id = ?", (OWNER_ID,))
        if not cursor.fetchone():
            admin_count += 1
            
        return {
            "total_users": total_users,
            "total_servers": total_servers,
            "total_admins": admin_count,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "api_status": "Online 🟢"
        }

# Initialize tables immediately on import
init_db()
