import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(os.path.join(LOG_DIR, "screenshots"), exist_ok=True)

_fmt = "[%(asctime)s] %(levelname)-7s %(message)s"
_datefmt = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger("hh_assistant")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=7, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_fmt, _datefmt))

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(_fmt, _datefmt))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


async def save_error_screenshot(page, name: str = "error"):
    try:
        path = os.path.join(LOG_DIR, "screenshots", f"{name}.png")
        await page.screenshot(path=path)
        logger.debug(f"Скриншот сохранён: {path}")
    except Exception:
        pass
