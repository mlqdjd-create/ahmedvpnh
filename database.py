import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_FILE = Path(__file__).resolve().parent / "ahmed_vpn.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create every table the app + bot need. Uses try/finally so the
    connection is always closed (the sqlite3 context manager only commits)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            protocol TEXT NOT NULL,
            config TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Per-server advanced fields (proxy / payload / country). Added later,
        # so migrate existing databases with ALTER TABLE.
        server_cols = {
            "country": "TEXT DEFAULT ''",
            "proxy_host": "TEXT DEFAULT ''",
            "proxy_port": "INTEGER DEFAULT 0",
            "proxy_user": "TEXT DEFAULT ''",
            "proxy_pass": "TEXT DEFAULT ''",
            "payload": "TEXT DEFAULT ''",
        }
        existing = {row["name"] for row in cursor.execute("PRAGMA table_info(servers)").fetchall()}
        for col, decl in server_cols.items():
            if col not in existing:
                try:
                    cursor.execute(f"ALTER TABLE servers ADD COLUMN {col} {decl}")
                except sqlite3.OperationalError:
                    pass

        # Installations / devices that pinged the backend
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            app_version TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Currently connected user -> server (used for per-server user counts)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_sessions (
            user_id TEXT PRIMARY KEY,
            server TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Raw activity log (connect/disconnect/...)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            server TEXT,
            event TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Broadcast announcements (the app polls the latest one)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Key/value settings (used for the forced app update)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        # روابط الاشتراك المدفوعة: كل توكن = مستخدم واحد، له تاريخ انتهاء
        # ويمكن ربطه بسيرفرات محددة (server_ids فارغ = كل السيرفرات).
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        conn.commit()
    finally:
        conn.close()


# ============================ SERVERS ============================

def add_server(name: str, protocol: str, config: str,
               country: str = "", proxy_host: str = "", proxy_port: int = 0,
               proxy_user: str = "", proxy_pass: str = "", payload: str = "") -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO servers
               (name, protocol, config, country, proxy_host, proxy_port, proxy_user, proxy_pass, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name.strip(), protocol.strip().upper(), config.strip(),
             (country or "").strip(), (proxy_host or "").strip(), int(proxy_port or 0),
             (proxy_user or "").strip(), proxy_pass or "", payload or ""),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_server_advanced(server_id: int, country: str = "", proxy_host: str = "",
                           proxy_port: int = 0, proxy_user: str = "",
                           proxy_pass: str = "", payload: str = "") -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE servers
               SET country = ?, proxy_host = ?, proxy_port = ?, proxy_user = ?, proxy_pass = ?, payload = ?
               WHERE id = ?""",
            ((country or "").strip(), (proxy_host or "").strip(), int(proxy_port or 0),
             (proxy_user or "").strip(), proxy_pass or "", payload or "", server_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


_SERVER_COLUMNS = ("id, name, protocol, config, created_at, country, "
                   "proxy_host, proxy_port, proxy_user, proxy_pass, payload")


def get_all_servers() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT {_SERVER_COLUMNS} FROM servers ORDER BY id DESC")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_server_by_id(server_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT {_SERVER_COLUMNS} FROM servers WHERE id = ?", (server_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_server(server_id: int) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM servers WHERE id = ?", (server_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_servers_count() -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS count FROM servers")
        row = cursor.fetchone()
        return row["count"] if row else 0
    finally:
        conn.close()


# ============================ USERS ============================

def upsert_user(user_id: str, app_version: str = "") -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO users (user_id, app_version, last_seen)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            app_version = excluded.app_version,
            last_seen = CURRENT_TIMESTAMP
        """, (str(user_id), app_version or ""))
        conn.commit()
    finally:
        conn.close()


def get_users_count() -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS count FROM users")
        row = cursor.fetchone()
        return row["count"] if row else 0
    finally:
        conn.close()


def log_activity(user_id: str, server: str, event: str) -> None:
    """Record activity and keep the active_sessions table in sync so that
    per-server live user counts stay accurate."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO activity (user_id, server, event) VALUES (?, ?, ?)",
            (str(user_id), server or "", event or ""),
        )
        if event == "connect":
            cursor.execute("""
            INSERT INTO active_sessions (user_id, server, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                server = excluded.server,
                updated_at = CURRENT_TIMESTAMP
            """, (str(user_id), server or ""))
        elif event == "disconnect":
            cursor.execute("DELETE FROM active_sessions WHERE user_id = ?", (str(user_id),))
        conn.commit()
    finally:
        conn.close()


def get_per_server_counts() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT server, COUNT(*) AS users
        FROM active_sessions
        GROUP BY server
        ORDER BY users DESC
        """)
        return [{"server": row["server"], "users": row["users"]} for row in cursor.fetchall()]
    finally:
        conn.close()


# ============================ ANNOUNCEMENTS ============================

def add_announcement(message: str) -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO announcements (message) VALUES (?)", (message.strip(),))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_latest_announcement() -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, message, created_at FROM announcements ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ============================ SETTINGS (app update) ============================

def set_setting(key: str, value: str) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


# ============================ SUBSCRIPTIONS ============================
# روابط الاشتراك المدفوعة: كل توكن يمثّل مستخدمًا واحدًا، له تاريخ انتهاء
# ويمكن ربطه بسيرفرات محددة. المستخدم يستلم رابطًا واحدًا (/sub/<token>)
# يستعمله في أي تطبيق v2ray و يتحدّث تلقائيًا عند إضافة/حذف السيرفرات.

def create_subscription(label: str, days: int = 0,
                        server_ids: str = "", note: str = "") -> Dict[str, Any]:
    """ينشئ توكن اشتراك جديد. days=0 يعني بلا انتهاء. server_ids نص مفصول
    بفواصل (فارغ = كل السيرفرات)."""
    token = secrets.token_urlsafe(24)
    expires = None
    if days and int(days) > 0:
        expires = (datetime.now() + timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO subscriptions (token, label, expires_at, server_ids, note, active)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (token, (label or "").strip(), expires,
             (server_ids or "").strip(), (note or "").strip()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"token": token, "label": label, "expires_at": expires,
            "server_ids": (server_ids or "").strip()}


def get_subscription(token: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE token = ?", (token,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_subscriptions() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions ORDER BY id DESC")
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def set_subscription_active(token: str, active: bool) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE subscriptions SET active = ? WHERE token = ?",
                       (1 if active else 0, token))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_subscription(token: str) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM subscriptions WHERE token = ?", (token,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def touch_subscription(token: str) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE subscriptions SET last_used = CURRENT_TIMESTAMP WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


# Initialize immediately on import
init_db()
