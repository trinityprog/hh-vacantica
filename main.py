import asyncio
import os
import signal
import sys
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

import browser
import config
import dashboard
import database
import negotiations
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
        if not await browser.is_logged_in(_page):
            logger.error("Сессия hh.ru недействительна (разлогин) — пропускаю задачу. Запустите: python main.py --login")
            return
        result = await resume.publish_resume(_page)
        logger.info(f"Поднятие резюме: поднято={result['raised']}, пропущено={result['skipped']}, ошибок={result['errors']}")
        stats = database.get_stats()
        logger.info(f"Статистика: всего откликов={stats['total_responses']}, сегодня={stats['today_responses']}")
    except Exception as e:
        logger.error(f"Ошибка в задаче поднятия резюме: {e}")


async def task_respond_to_vacancies(profile_name: str | None = None):
    global _page
    try:
        if _page is None:
            logger.error("Страница браузера не инициализирована")
            return
        if config.RESPOND_ACTIVE_HOURS and profile_name is None:
            start, end = config.RESPOND_ACTIVE_HOURS
            hour = datetime.now(pytz.timezone(config.TIMEZONE)).hour
            if not (start <= hour < end):
                logger.info(f"Вне активных часов {start}:00–{end}:00 — пропускаю прогон")
                return
        if not await browser.is_logged_in(_page):
            logger.error("Сессия hh.ru недействительна (разлогин) — пропускаю задачу. Запустите: python main.py --login")
            return
        # hh.ru может обновлять куки сессии — сохраняем свежие, чтобы после перезапуска не потерять вход
        await browser.save_session(_page)
        stats = await vacancies.run_responses(_page, profile_name)
        logger.info(
            f"Итог откликов: отправлено={stats['sent']}, пропущено={stats['skipped']}, "
            f"на ручную обработку={stats['manual']}, ошибок={stats['errors']}"
        )
    except Exception as e:
        logger.error(f"Ошибка в задаче откликов: {e}")


async def task_sync_negotiations():
    global _page
    try:
        if _page is None:
            logger.error("Страница браузера не инициализирована")
            return
        if not await browser.is_logged_in(_page):
            logger.error("Сессия hh.ru недействительна (разлогин) — пропускаю задачу. Запустите: python main.py --login")
            return
        await negotiations.sync_statuses(_page)
        await negotiations.sync_unread_chats(_page)
    except Exception as e:
        logger.error(f"Ошибка в задаче синхронизации статусов: {e}")


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

    scheduler.add_job(
        task_respond_to_vacancies,
        IntervalTrigger(
            minutes=config.VACANCY_INTERVAL_MINUTES,
            jitter=config.VACANCY_INTERVAL_JITTER_SECONDS,
            timezone=tz,
        ),
        id="vacancies_interval",
        name=f"Отклики каждые {config.VACANCY_INTERVAL_MINUTES} мин",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(tz),   # первый прогон сразу при старте, не через интервал
    )

    scheduler.add_job(
        task_sync_negotiations,
        IntervalTrigger(minutes=config.NEGOTIATIONS_SYNC_INTERVAL_MINUTES, timezone=tz),
        id="negotiations_sync",
        name=f"Синхронизация статусов откликов каждые {config.NEGOTIATIONS_SYNC_INTERVAL_MINUTES} мин",
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    logger.info(
        f"Планировщик запущен. Резюме: {config.RESUME_SCHEDULE_TIMES}, "
        f"Отклики: каждые {config.VACANCY_INTERVAL_MINUTES} мин, часы {config.RESPOND_ACTIVE_HOURS or 'круглосуточно'}, "
        f"Синхронизация статусов: каждые {config.NEGOTIATIONS_SYNC_INTERVAL_MINUTES} мин"
    )


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
    _, ctx = await browser.load_session(headless=False)  # вход вручную — окно должно быть видно
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


async def run_now_respond(profile_name: str | None = None):
    """Немедленный запуск откликов (режим тестирования). profile_name — профиль поиска из config."""
    global _page
    await browser.start_playwright()
    _, ctx = await browser.load_session()
    _page = await ctx.new_page()

    if not await browser.is_logged_in(_page):
        logger.error("Сессия недействительна. Запустите: python main.py --login")
        await browser.stop_playwright()
        return

    await task_respond_to_vacancies(profile_name)
    await browser.stop_playwright()


async def run_retry_manual(profile_name: str | None = None):
    """Повторно прогнать вакансии из списка «На ручную обработку»."""
    await browser.start_playwright()
    _, ctx = await browser.load_session()
    page = await ctx.new_page()

    if not await browser.is_logged_in(page):
        logger.error("Сессия недействительна. Запустите: python main.py --login")
        await browser.stop_playwright()
        return

    stats = await vacancies.retry_manual_review(page, profile_name or "non_dev")
    logger.info(
        f"Итог повторного прогона: отправлено={stats['sent']}, пропущено={stats['skipped']}, "
        f"осталось в ручных={stats['manual']}, ошибок={stats['errors']}"
    )
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

    port = int(os.getenv("DASHBOARD_PORT", "8888"))
    dashboard.start_dashboard(port=port)
    logger.info(f"Дашборд запущен: http://0.0.0.0:{port}")

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
    elif "--retry-manual" in args:
        database.init_db()
        profile_name = args[args.index("--profile") + 1] if "--profile" in args else None
        asyncio.run(run_retry_manual(profile_name))
    elif "--now-respond" in args:
        database.init_db()
        profile_name = args[args.index("--profile") + 1] if "--profile" in args else None
        asyncio.run(run_now_respond(profile_name))
    else:
        try:
            asyncio.run(run_scheduler())
        except KeyboardInterrupt:
            logger.info("Остановлено пользователем.")


if __name__ == "__main__":
    main()
