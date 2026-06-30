import os
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

import config
from logger import logger

_playwright = None
_browser: Browser | None = None
_context: BrowserContext | None = None


async def start_playwright():
    global _playwright
    _playwright = await async_playwright().start()
    return _playwright


async def stop_playwright():
    global _playwright, _browser, _context
    try:
        if _context:
            await _context.close()
        if _browser:
            await _browser.close()
        if _playwright:
            await _playwright.stop()
    except Exception as e:
        logger.warning(f"Ошибка при закрытии браузера: {e}")
    finally:
        _playwright = None
        _browser = None
        _context = None


async def save_session(page: Page):
    os.makedirs(os.path.dirname(config.SESSION_PATH), exist_ok=True)
    await page.context.storage_state(path=config.SESSION_PATH)
    logger.info(f"Сессия сохранена: {config.SESSION_PATH}")


async def load_session() -> tuple[Browser, BrowserContext]:
    global _playwright, _browser, _context
    if _playwright is None:
        await start_playwright()

    _browser = await _playwright.chromium.launch(headless=config.HEADLESS)

    if os.path.exists(config.SESSION_PATH):
        logger.info("Загружаю сохранённую сессию")
        _context = await _browser.new_context(storage_state=config.SESSION_PATH)
    else:
        logger.info("Сессия не найдена, создаю новый контекст")
        _context = await _browser.new_context()

    return _browser, _context


async def new_page() -> Page:
    if _context is None:
        raise RuntimeError("Браузерный контекст не инициализирован. Вызовите load_session() сначала.")
    page = await _context.new_page()
    return page


async def is_logged_in(page: Page) -> bool:
    try:
        await page.goto("https://hh.ru/applicant/resumes", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        return "login" not in page.url and "account" not in page.url
    except Exception as e:
        logger.error(f"Ошибка проверки авторизации: {e}")
        return False


async def login_manually(page: Page):
    """Открыть страницу входа и дождаться ручного входа пользователя."""
    logger.info("Открываю страницу входа. Войдите вручную в браузере.")
    await page.goto("https://hh.ru/account/login", wait_until="domcontentloaded")

    logger.info("Ожидаю завершения входа (до 5 минут)...")
    try:
        await page.wait_for_url("**/applicant/**", timeout=300_000)
        logger.info("Вход выполнен успешно!")
    except Exception:
        # Даже если URL не совпал — проверим вручную
        if await is_logged_in(page):
            logger.info("Вход выполнен успешно!")
        else:
            raise RuntimeError("Время ожидания входа истекло или вход не выполнен.")
