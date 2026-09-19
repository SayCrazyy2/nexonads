import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import (
    ADMIN_ID,
    BOT_TOKEN,
    DB_PATH,
    RAILWAY_BUCKET_ACCESS_KEY,
    RAILWAY_BUCKET_ENDPOINT,
    RAILWAY_BUCKET_NAME,
    RAILWAY_BUCKET_PREFIX,
    RAILWAY_BUCKET_REGION,
    RAILWAY_BUCKET_SECRET_KEY,
    SESSIONS_DIR,
)
from persistence import BucketPersistence

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    if not BOT_TOKEN or BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("Set BOT_TOKEN in config.py")

    persistence = BucketPersistence(
        db_path=DB_PATH,
        sessions_dir=SESSIONS_DIR,
        endpoint=RAILWAY_BUCKET_ENDPOINT,
        bucket=RAILWAY_BUCKET_NAME,
        access_key=RAILWAY_BUCKET_ACCESS_KEY,
        secret_key=RAILWAY_BUCKET_SECRET_KEY,
        region=RAILWAY_BUCKET_REGION,
        prefix=RAILWAY_BUCKET_PREFIX,
    )
    persistence.restore()

    from handlers import am, db, router

    if ADMIN_ID:
        db.add_user(ADMIN_ID, "admin", is_sudo=1)
        db.set_approval(ADMIN_ID, True, ADMIN_ID)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Starting polling")
        await dp.start_polling(bot)
    finally:
        try:
            await am.disconnect_all()
        finally:
            db.close()
            persistence.sync()
            await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
