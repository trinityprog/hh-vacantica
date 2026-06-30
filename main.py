import asyncio
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import browser
import config
import dashboard
import database
import resume
import vacancies
from logger import logger


scheduler: AsyncIOScheduler | None = None
_page = None


async def task_publish_resume():
    global _page
    try:
        if _page is None:
            logger.error("Страница браузера не инициализирована")
            return
        result = await resume.publish_resume(_page)
        logger.info(f"Поднятие резюме: поднято={result['raised']}, пропущено={result['skipped']}, ошибок={result['errors']}")
        stats = database.get_stats()
        logger.info(f"Статистика: всего откликов={stats['total_responses']}, сегодня={stats['today_responses']}")
    except Exception as e:
        logger.error(f"Ошибка в задаче поднятия резюме: {e}")


async def task_respond_to_vacancies():
    global _page
    try:
        if _page is None:
            logger.error("Страница браузера не инициализирована")
            return
        stats = await vacancies.run_responses(_page)
        logger.info(f"Итог откликов: отправлено={stats['sent']}, пропущено={stats['skipped']}, ошибок={stats['errors']}")
    except Exception as e:
        logger.error(f"Ошибка в задаче откликов: {e}")


async def setup_scheduler():
    global scheduler
    tz = pytz.timezone(config.TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)

    for time_str in config.RESUME_SCHEDULE_TIMES:
        hour, minute = time_str.split(":")
        scheduler.add_job(
            task_publish_resume,
            CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
            id=f"resume_{time_str}",
            name=f"Поднятие резюме {time_str}",
        )

    for time_str in config.VACANCY_SCHEDULE_TIMES:
        hour, minute = time_str.split(":")
        scheduler.add_job(
            task_respond_to_vacancies,
            CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
            id=f"vacancies_{time_str}",
            name=f"Отклики {time_str}",
        )

    scheduler.start()
    logger.info(f"Планировщик запущен. Резюме: {config.RESUME_SCHEDULE_TIMES}, Отклики: {config.VACANCY_SCHEDULE_TIMES}")


async def shutdown():
    logger.info("Завершение работы...")
    if scheduler:
        scheduler.shutdown(wait=False)
    await browser.stop_playwright()
    logger.info("Работа завершена.")


async def run_login():
    """Режим первого входа — ручная авторизация."""
    logger.info("Режим авторизации: откроется браузер, войдите вручную.")
    await browser.start_playwright()
    _, ctx = await browser.load_session()
    page = await ctx.new_page()
    await browser.login_manually(page)
    await browser.save_session(page)
    await browser.stop_playwright()
    logger.info("Авторизация завершена. Сессия сохранена.")


async def run_now_publish():
    """Немедленное поднятие резюме (режим тестирования)."""
    global _page
    await browser.start_playwright()
    _, ctx = await browser.load_session()
    _page = await ctx.new_page()

    if not await browser.is_logged_in(_page):
        logger.error("Сессия недействительна. Запустите: python main.py --login")
        await browser.stop_playwright()
        return

    await task_publish_resume()
    await browser.stop_playwright()


async def run_now_respond():
    """Немедленный запуск откликов (режим тестирования)."""
    global _page
    await browser.start_playwright()
    _, ctx = await browser.load_session()
    _page = await ctx.new_page()

    if not await browser.is_logged_in(_page):
        logger.error("Сессия недействительна. Запустите: python main.py --login")
        await browser.stop_playwright()
        return

    await task_respond_to_vacancies()
    await browser.stop_playwright()


async def run_scheduler():
    """Основной режим — планировщик работает непрерывно."""
    global _page
    database.init_db()

    await browser.start_playwright()
    _, ctx = await browser.load_session()
    _page = await ctx.new_page()

    if not await browser.is_logged_in(_page):
        logger.error("Сессия недействительна. Запустите: python main.py --login")
        await browser.stop_playwright()
        return

    logger.info("Авторизация подтверждена.")
    stats = database.get_stats()
    logger.info(f"База данных: {stats}")

    dashboard.start_dashboard(port=8888)
    logger.info("Дашборд запущен: http://0.0.0.0:8888")

    await setup_scheduler()

    loop = asyncio.get_event_loop()

    def _handle_signal():
        asyncio.ensure_future(shutdown())
        loop.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    logger.info("Ожидаю расписания. Нажмите Ctrl+C для остановки.")
    try:
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass
    finally:
        await shutdown()


def main():
    args = sys.argv[1:]

    if "--login" in args:
        asyncio.run(run_login())
    elif "--now-publish" in args:
        database.init_db()
        asyncio.run(run_now_publish())
    elif "--now-respond" in args:
        database.init_db()
        asyncio.run(run_now_respond())
    else:
        try:
            asyncio.run(run_scheduler())
        except KeyboardInterrupt:
            logger.info("Остановлено пользователем.")


if __name__ == "__main__":
    main()
