import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_FILE = Path(__file__).resolve().parent / "ahmed_vpn.db"

def get_connection():
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
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
        conn.commit()

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

# Initialize immediately on import
init_db()
