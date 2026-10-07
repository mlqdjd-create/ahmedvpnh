import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

# ============================================================================
# طبقة قاعدة البيانات — تدعم PostgreSQL (Supabase) + SQLite كاحتياط.
# إذا وُجد DATABASE_URL يبدأ بـ postgres، نستعمل PostgreSQL (بيانات دائمة
# تبقى حتى لو الاستضافة طفت). وإلا نرجع لملف SQLite محلي (للتطوير فقط).
# ============================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_POSTGRES = DATABASE_URL.lower().startswith(("postgres://", "postgresql://"))
if IS_POSTGRES and "sslmode=" not in DATABASE_URL:
    DATABASE_URL += ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"

DB_FILE = Path(__file__).resolve().parent / "ahmed_vpn.db"

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras

_AUTOINC = "SERIAL PRIMARY KEY" if IS_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"


def get_connection():
    if IS_POSTGRES:
        return psycopg2.connect(DATABASE_URL, connect_timeout=20)
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn


def _cur(conn):
    if IS_POSTGRES:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # ✅ نجعل صفوف SQLite تدعم الوصول بالمفتاح والفهرس معًا (dict(row) و row[0])
    try:
        conn.row_factory = sqlite3.Row
    except Exception:
        pass
    return conn.cursor()


def _s(sql: str) -> str:
    """يحوّل علامات الاستفهام ? إلى %s لـPostgreSQL."""
    return sql.replace("?", "%s") if IS_POSTGRES else sql


_SERVER_COLUMNS = ("id, name, protocol, config, created_at, country, "
                   "proxy_host, proxy_port, proxy_user, proxy_pass, payload, category")


def init_db() -> None:
    """Create every table the app + bot need (works on both engines)."""
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS servers (
            id {_AUTOINC},
            name TEXT NOT NULL,
            protocol TEXT NOT NULL,
            config TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()
        # Per-server extra fields (proxy / payload / country / category).
        # category: 'main' = يظهر لكل مستخدمي التطبيق، 'sub' = سيرفرات الاشتراك فقط (معزولة).
        server_cols = {
            "country": "TEXT DEFAULT ''",
            "proxy_host": "TEXT DEFAULT ''",
            "proxy_port": "INTEGER DEFAULT 0",
            "proxy_user": "TEXT DEFAULT ''",
            "proxy_pass": "TEXT DEFAULT ''",
            "payload": "TEXT DEFAULT ''",
            "category": "TEXT DEFAULT 'main'",
        }
        if IS_POSTGRES:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'servers'")
            existing = {r["column_name"] for r in cur.fetchall()}
        else:
            cur.execute("PRAGMA table_info(servers)")
            existing = {r["name"] for r in cur.fetchall()}
        for col, decl in server_cols.items():
            if col not in existing:
                try:
                    cur.execute(f"ALTER TABLE servers ADD COLUMN {col} {decl}")
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass

        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            app_version TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS active_sessions (
            user_id TEXT PRIMARY KEY,
            server TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS activity (
            id {_AUTOINC},
            user_id TEXT,
            server TEXT,
            event TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS announcements (
            id {_AUTOINC},
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id {_AUTOINC},
            token TEXT UNIQUE NOT NULL,
            label TEXT DEFAULT '',
            note TEXT DEFAULT '',
            server_ids TEXT DEFAULT '',
            expires_at TIMESTAMP,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()
    finally:
        conn.close()


# ============================ SERVERS ============================

def add_server(name: str, protocol: str, config: str,
               country: str = "", proxy_host: str = "", proxy_port: int = 0,
               proxy_user: str = "", proxy_pass: str = "", payload: str = "",
               category: str = "main") -> int:
    conn = get_connection()
    try:
        cur = _cur(conn)
        sql = """INSERT INTO servers
               (name, protocol, config, country, proxy_host, proxy_port, proxy_user, proxy_pass, payload, category)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        params = (name.strip(), protocol.strip().upper(), config.strip(),
                  (country or "").strip(), (proxy_host or "").strip(), int(proxy_port or 0),
                  (proxy_user or "").strip(), proxy_pass or "", payload or "",
                  (category or "main").strip())
        if IS_POSTGRES:
            cur.execute(_s(sql) + " RETURNING id", params)
            row = cur.fetchone()
            conn.commit()
            return row["id"]
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_server_advanced(server_id: int, country: str = "", proxy_host: str = "",
                           proxy_port: int = 0, proxy_user: str = "",
                           proxy_pass: str = "", payload: str = "") -> bool:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("""
            UPDATE servers
               SET country = ?, proxy_host = ?, proxy_port = ?, proxy_user = ?, proxy_pass = ?, payload = ?
             WHERE id = ?
        """), ((country or "").strip(), (proxy_host or "").strip(), int(proxy_port or 0),
               (proxy_user or "").strip(), proxy_pass or "", payload or "", server_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_all_servers(category: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = _cur(conn)
        if category:
            cur.execute(_s(f"SELECT {_SERVER_COLUMNS} FROM servers WHERE category = ? ORDER BY id DESC"),
                        (category,))
        else:
            cur.execute(f"SELECT {_SERVER_COLUMNS} FROM servers ORDER BY id DESC")
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_server_by_id(server_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s(f"SELECT {_SERVER_COLUMNS} FROM servers WHERE id = ?"), (server_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_server(server_id: int) -> bool:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("DELETE FROM servers WHERE id = ?"), (server_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_servers_count(category: Optional[str] = None) -> int:
    conn = get_connection()
    try:
        cur = _cur(conn)
        if category:
            cur.execute(_s("SELECT COUNT(*) AS count FROM servers WHERE category = ?"), (category,))
        else:
            cur.execute("SELECT COUNT(*) AS count FROM servers")
        row = cur.fetchone()
        return row["count"] if row else 0
    finally:
        conn.close()


# ============================ USERS ============================

def upsert_user(user_id: str, app_version: str = "") -> None:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("""
        INSERT INTO users (user_id, app_version, last_seen)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            app_version = excluded.app_version,
            last_seen = CURRENT_TIMESTAMP
        """), (str(user_id), app_version or ""))
        conn.commit()
    finally:
        conn.close()


def get_users_count() -> int:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute("SELECT COUNT(*) AS count FROM users")
        row = cur.fetchone()
        return row["count"] if row else 0
    finally:
        conn.close()


def log_activity(user_id: str, server: str, event: str) -> None:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("INSERT INTO activity (user_id, server, event) VALUES (?, ?, ?)"),
                    (str(user_id), server or "", event or ""))
        if event == "connect":
            cur.execute(_s("""
            INSERT INTO active_sessions (user_id, server, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                server = excluded.server,
                updated_at = CURRENT_TIMESTAMP
            """), (str(user_id), server or ""))
        elif event == "disconnect":
            cur.execute(_s("DELETE FROM active_sessions WHERE user_id = ?"), (str(user_id),))
        conn.commit()
    finally:
        conn.close()


def get_per_server_counts() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute("""
        SELECT server, COUNT(*) AS users
        FROM active_sessions
        GROUP BY server
        ORDER BY users DESC
        """)
        return [{"server": row["server"], "users": row["users"]} for row in cur.fetchall()]
    finally:
        conn.close()


# ============================ ANNOUNCEMENTS ============================

def add_announcement(message: str) -> int:
    conn = get_connection()
    try:
        cur = _cur(conn)
        sql = "INSERT INTO announcements (message) VALUES (?)"
        if IS_POSTGRES:
            cur.execute(_s(sql) + " RETURNING id", (message.strip(),))
            row = cur.fetchone()
            conn.commit()
            return row["id"]
        cur.execute(sql, (message.strip(),))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_latest_announcement() -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute("SELECT id, message, created_at FROM announcements ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ============================ SETTINGS (app update) ============================

def set_setting(key: str, value: str) -> None:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("""
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """), (key, value))
        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("SELECT value FROM settings WHERE key = ?"), (key,))
        row = cur.fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


# ============================ SUBSCRIPTIONS ============================
# روابط الاشتراك المدفوعة: كل توكن يمثّل مستخدمًا واحدًا، له تاريخ انتهاء.
# تُبنى من سيرفرات الاشتراك (category='sub') فقط — معزولة عن سيرفرات التطبيق.

def create_subscription(label: str, days: int = 0,
                        server_ids: str = "", note: str = "") -> Dict[str, Any]:
    token = secrets.token_urlsafe(24)
    expires = None
    if days and int(days) > 0:
        expires = (datetime.now() + timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("""
        INSERT INTO subscriptions (token, label, expires_at, server_ids, note, active)
        VALUES (?, ?, ?, ?, ?, 1)
        """), (token, (label or "").strip(), expires,
               (server_ids or "").strip(), (note or "").strip()))
        conn.commit()
    finally:
        conn.close()
    return {"token": token, "label": label, "expires_at": expires,
            "server_ids": (server_ids or "").strip()}


def get_subscription(token: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("SELECT * FROM subscriptions WHERE token = ?"), (token,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_subscriptions() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute("SELECT * FROM subscriptions ORDER BY id DESC")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def set_subscription_active(token: str, active: bool) -> bool:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("UPDATE subscriptions SET active = ? WHERE token = ?"),
                    (1 if active else 0, token))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_subscription(token: str) -> bool:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("DELETE FROM subscriptions WHERE token = ?"), (token,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def touch_subscription(token: str) -> None:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("UPDATE subscriptions SET last_used = CURRENT_TIMESTAMP WHERE token = ?"), (token,))
        conn.commit()
    finally:
        conn.close()


# ============================ ADMINS ============================
# مدراء متعددون للوحة/البوت. المالك (OWNER_ID) دائمًا مدير ولا يُحذف.

def add_admin(user_id, name: str = "") -> None:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("""
        INSERT INTO admins (user_id, name) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET name = excluded.name
        """), (str(user_id), (name or "").strip()))
        conn.commit()
    finally:
        conn.close()


def remove_admin(user_id) -> bool:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("DELETE FROM admins WHERE user_id = ?"), (str(user_id),))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_admins() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute("SELECT user_id, name, added_at FROM admins ORDER BY added_at ASC")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def is_admin(user_id) -> bool:
    conn = get_connection()
    try:
        cur = _cur(conn)
        cur.execute(_s("SELECT 1 FROM admins WHERE user_id = ?"), (str(user_id),))
        return cur.fetchone() is not None
    finally:
        conn.close()


# Initialize immediately on import (لا يوقف التشغيل إذا فشل الاتصال مؤقتًا).
try:
    init_db()
except Exception as _e:
    print(f"[database] WARNING: init_db failed: {_e}")
