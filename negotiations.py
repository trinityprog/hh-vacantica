import re
import unicodedata

import browser
import database
from logger import logger

STATUS_MAP = {
    "negotiations-item-not-viewed": "Не просмотрен",
    "negotiations-item-viewed": "Просмотрен",
    "negotiations-item-interview": "Собеседование",
    "negotiations-item-discard": "Отказ",
}

MAX_PAGES = 30  # запас на случай большого числа откликов


async def sync_statuses(page) -> dict:
    """
    Пройтись по списку откликов hh.ru (/applicant/negotiations) и обновить
    статус (Просмотрен/Не просмотрен/Собеседование/Отказ) для уже отправленных
    откликов в БД. Не заходит в чаты — только список.
    """
    stats = {"updated": 0, "pages": 0}

    is_limited, blocked_until, block_reason = database.get_rate_limit_status()
    if is_limited:
        logger.info(f"Блокировка активна до {blocked_until} UTC ({block_reason}) — пропускаю синхронизацию статусов")
        return stats

    try:
        if await browser.is_ddos_challenge(page):
            logger.warning("DDoS-Guard при синхронизации статусов откликов — пропускаю")
            return stats

        for page_num in range(MAX_PAGES):
            url = f"https://hh.ru/applicant/negotiations?page={page_num}"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)

            items = await page.evaluate("""() => {
                const items = [...document.querySelectorAll("[data-qa='negotiations-item']")];
                return items.map(item => {
                    const tagEl = item.querySelector("[data-qa*='negotiations-tag']");
                    const vacancyLink = [...item.querySelectorAll('a')]
                        .map(a => a.href)
                        .find(h => h && h.includes('/vacancy/'));
                    return {
                        tagQa: tagEl ? tagEl.getAttribute('data-qa') : null,
                        vacancyHref: vacancyLink || null,
                    };
                });
            }""")

            if not items:
                break

            stats["pages"] += 1
            for item in items:
                if not item["vacancyHref"] or not item["tagQa"]:
                    continue
                match = re.search(r"/vacancy/(\d+)", item["vacancyHref"])
                if not match:
                    continue
                vacancy_id = match.group(1)
                tag_qa = item["tagQa"].split()[-1]  # "negotiations-tag negotiations-item-viewed" -> последнее
                status = STATUS_MAP.get(tag_qa)
                if not status:
                    continue
                if database.is_already_responded(vacancy_id):
                    database.update_response_status(vacancy_id, status)
                    stats["updated"] += 1

            if len(items) < 20:
                # последняя страница
                break

        logger.info(f"Синхронизация статусов откликов: обновлено={stats['updated']}, страниц={stats['pages']}")

    except Exception as e:
        logger.error(f"Ошибка синхронизации статусов откликов: {e}")

    return stats


def _normalize(text: str | None) -> str:
    """Убрать невидимые unicode-символы (hh.ru вставляет zero-width space в заголовки) и привести к нижнему регистру."""
    if not text:
        return ""
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return text.strip().lower()


async def sync_unread_chats(page) -> dict:
    """
    Открыть виджет чатов (iframe chatik.hh.ru), включить фильтр "только непрочитанные"
    и сопоставить найденные чаты с откликами в БД по названию вакансии + компании.
    Это не 100%-но точный сигнал "бот ждёт ответа", но непрочитанное входящее
    сообщение — практически всегда именно это.
    """
    stats = {"unread": 0, "matched": 0}

    is_limited, blocked_until, block_reason = database.get_rate_limit_status()
    if is_limited:
        logger.info(f"Блокировка активна до {blocked_until} UTC ({block_reason}) — пропускаю синхронизацию чатов")
        return stats

    try:
        await page.goto("https://hh.ru/applicant/negotiations", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        if await browser.is_ddos_challenge(page):
            logger.warning("DDoS-Guard при синхронизации чатов — пропускаю")
            return stats

        await page.click("[data-qa='chatik-activator']", force=True, timeout=15000)
        await page.wait_for_timeout(4000)

        chat_frame = next((f for f in page.frames if "chatik.hh.ru" in f.url), None)
        if not chat_frame:
            logger.warning("Не удалось найти фрейм чата для синхронизации")
            return stats

        try:
            await chat_frame.click("[data-qa='chatik-checkbox-only-unread']", force=True, timeout=10000)
            await page.wait_for_timeout(2500)
        except Exception:
            logger.warning("Не удалось включить фильтр 'только непрочитанные'")
            return stats

        unread_items = await chat_frame.evaluate("""() => {
            const items = [...document.querySelectorAll('[data-qa]')]
                .filter(e => e.getAttribute('data-qa').startsWith('chatik-open-chat-'));
            return items.map(item => {
                const cell = item.closest("[data-qa='cell']") || item;
                const title = cell.querySelector("[data-qa='chat-cell-title']")?.innerText || null;
                const company = cell.querySelector("[data-qa='chat-cell-subtitle']")?.innerText || null;
                const msgEl = cell.querySelector("[class*='last-message']:not([class*='wrapper'])");
                const lastMessage = msgEl ? msgEl.innerText : null;
                return { title, company, lastMessage, chatUrl: item.href || null };
            });
        }""")

        # Отсеиваем чаты без реального сообщения — только системные ярлыки
        # ("Отклик на вакансию", "Отказ") без переписки не считаем "ждущими ответа"
        GENERIC_LABELS = {"отклик на вакансию", "отказ", "приглашение"}
        unread_items = [
            i for i in unread_items
            if (i["lastMessage"] or "").strip().lower() not in GENERIC_LABELS
        ]

        stats["unread"] = len(unread_items)
        unread_by_key = {
            (_normalize(i["title"]), _normalize(i["company"])): i
            for i in unread_items
        }

        database.reset_unread()
        for row in database.get_response_keys():
            key = (_normalize(row["vacancy_title"]), _normalize(row["company_name"]))
            match = unread_by_key.get(key)
            if match:
                database.set_unread(row["vacancy_id"], match["chatUrl"] or "", match["lastMessage"] or "")
                stats["matched"] += 1

        logger.info(f"Синхронизация чатов: непрочитанных в hh.ru={stats['unread']}, сопоставлено с откликами={stats['matched']}")

    except Exception as e:
        logger.error(f"Ошибка синхронизации чатов: {e}")

    return stats
