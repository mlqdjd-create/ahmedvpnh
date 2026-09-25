import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

# Load environment variables
load_dotenv(dotenv_path=ENV_PATH)

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()

OWNER_ID_RAW: str = os.getenv("OWNER_ID", "6803988521").strip()
try:
    OWNER_ID: int = int(OWNER_ID_RAW)
except ValueError:
    OWNER_ID: int = 6803988521

ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "ahmed_vpn_admin_secret_key_2026").strip()

HOST: str = os.getenv("HOST", "0.0.0.0").strip()
PORT: int = int(os.getenv("PORT", "8080"))

DB_FILE: Path = BASE_DIR / "ahmed_vpn.db"

APP_NAME: str = "AHMED VPN"
VERSION: str = "2.0.0"
