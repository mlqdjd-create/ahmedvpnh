import sys
import threading
import logging
import uvicorn

import config
import database

# Configure root logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("AhmedVpnRunner")

def run_api_server():
    logger.info(f"🌐 Starting FastAPI on http://{config.HOST}:{config.PORT}")
    uvicorn.run("api:app", host=config.HOST, port=config.PORT, log_level="info")

def main():
    print("=" * 65)
    print(f"  🚀 {config.APP_NAME} v{config.VERSION}")
    print("  Unified Server (FastAPI + Telegram Admin Bot)")
    print(f"  Owner ID: {config.OWNER_ID}")
    print(f"  API Endpoint: http://{config.HOST}:{config.PORT}/api/servers")
    print("=" * 65)

    # Initialize Database
    database.init_db()

    # If BOT_TOKEN is empty or default, run API in foreground
    if not config.BOT_TOKEN or config.BOT_TOKEN == "ضع_توكن_البوت_هنا":
        print("\n" + "!" * 65)
        print(" [!] ملاحظة: لم يتم إدخال BOT_TOKEN داخل ملف .env بعد.")
        print(f" [!] المسار: {config.ENV_PATH}")
        print(" [!] سيعمل سيرفر الـ API حالياً لخدمة تطبيق الأندرويد.")
        print(" [!] لتشغيل البوت، ضع التوكن ثم أعد تشغيل run.py")
        print("!" * 65 + "\n")
        run_api_server()
        return

    # Start API in daemon thread
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()

    # Run Bot on main thread
    logger.info("🤖 Starting Telegram Admin Bot...")
    import bot
    bot.main()

if __name__ == "__main__":
    main()
