import datetime
import os

import browser
import config
import database
import human_delay
from logger import logger, save_error_screenshot


async def publish_resume(page) -> dict:
    """
    Поднять все резюме в поиске.
    Возвращает {"raised": int, "skipped": int, "errors": int}
    """
    stats = {"raised": 0, "skipped": 0, "errors": 0}

    is_limited, blocked_until, block_reason = database.get_rate_limit_status()
    if is_limited:
        logger.info(f"Блокировка активна до {blocked_until} UTC ({block_reason}) — пропускаю поднятие резюме")
        return stats

    try:
        logger.info("Запуск задачи: поднятие резюме")
        await page.goto("https://hh.ru/applicant/resumes", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        if await browser.is_ddos_challenge(page):
            reason = "DDoS-Guard проверка браузера на странице резюме"
            logger.warning(f"{reason} — откладываю попытки")
            database.set_rate_limited(config.RATE_LIMIT_BACKOFF_MINUTES, reason)
            await save_error_screenshot(page, "resume_ddos_guard")
            return stats

        resume_blocks = await _find_all_resume_blocks(page)
        if not resume_blocks:
            msg = "Резюме не найдены на странице"
            logger.error(msg)
            await save_error_screenshot(page, "resume_not_found")
            database.save_publish(False, msg)
            return stats

        logger.info(f"Найдено резюме: {len(resume_blocks)}")

        for title, block in resume_blocks:
            raise_btn = await _find_raise_button(block)

            if raise_btn is None:
                logger.warning(f"⏳ \"{title}\" — ещё нельзя поднять (< 4 часов)")
                database.save_publish(False, f"⏳ {title}: < 4 часов")
                stats["skipped"] += 1
                continue

            try:
                await human_delay.scroll_naturally(page)
                await raise_btn.click()
                await page.wait_for_timeout(2000)

                raise_btn_after = await _find_raise_button(block)
                if raise_btn_after is None:
                    msg = f'✅ Резюме поднято: "{title}"'
                    logger.info(msg)
                    database.save_publish(True, msg)
                    await _take_screenshot(page, "resume_raised")
                    stats["raised"] += 1
                else:
                    msg = f'"{title}" — кнопка осталась активной'
                    logger.warning(msg)
                    database.save_publish(False, msg)
                    stats["errors"] += 1

                # Пауза между поднятиями разных резюме
                if len(resume_blocks) > 1:
                    await human_delay.short_pause(3, 7)

            except Exception as e:
                msg = f"Ошибка при поднятии \"{title}\": {e}"
                logger.error(msg)
                await save_error_screenshot(page, "resume_error")
                database.save_publish(False, msg)
                stats["errors"] += 1

    except Exception as e:
        msg = f"Критическая ошибка в publish_resume: {e}"
        logger.error(msg)
        await save_error_screenshot(page, "resume_error")

    return stats


async def _find_all_resume_blocks(page) -> list[tuple[str, object]]:
    """Найти все блоки резюме на странице. Возвращает список (title, element)."""
    result = []
    try:
        blocks = await page.query_selector_all("[data-qa='resume']")
        for block in blocks:
            title_el = await block.query_selector("[data-qa='resume-title']")
            title = (await title_el.inner_text()).strip() if title_el else "Без названия"
            result.append((title, block))

    except Exception as e:
        logger.debug(f"_find_all_resume_blocks error: {e}")
    return result


async def _find_raise_button(container):
    """Найти активную кнопку поднятия резюме в блоке."""
    if container is None:
        return None
    try:
        selectors = [
            "[data-qa='resume-update-button_actions']",
            "button[data-qa='resume-update-button_actions']",
            "button:has-text('Поднять в поиске')",
        ]
        for sel in selectors:
            btn = await container.query_selector(sel)
            if btn:
                is_disabled = await btn.get_attribute("disabled")
                if is_disabled is None:
                    return btn
        return None
    except Exception as e:
        logger.debug(f"_find_raise_button error: {e}")
        return None


async def _take_screenshot(page, name: str):
    try:
        log_dir = os.path.join(os.path.dirname(__file__), "logs", "screenshots")
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        await page.screenshot(path=os.path.join(log_dir, f"{name}_{ts}.png"))
    except Exception:
        pass
