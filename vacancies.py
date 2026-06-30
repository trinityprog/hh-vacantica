import asyncio
import urllib.parse
from datetime import date

import config
import database
import human_delay
from logger import logger, save_error_screenshot


async def run_responses(page) -> dict:
    """
    Найти вакансии и откликнуться на подходящие.
    Возвращает {"sent": int, "skipped": int, "errors": int}
    """
    stats = {"sent": 0, "skipped": 0, "errors": 0}
    logger.info("Запуск задачи: отклики на вакансии")

    try:
        vacancies = await _search_vacancies(page)
        if not vacancies:
            logger.info("Вакансии не найдены")
            return stats

        filtered = _filter_vacancies(vacancies)
        logger.info(f"Найдено {len(vacancies)} вакансий, после фильтрации: {len(filtered)}")

        for vacancy in filtered:
            if stats["sent"] >= config.MAX_RESPONSES_PER_RUN:
                logger.info(f"Лимит откликов за запуск достигнут ({stats['sent']}/{config.MAX_RESPONSES_PER_RUN})")
                break

            if database.is_already_responded(vacancy["vacancy_id"]):
                logger.warning(f"⏭  Пропуск (уже откликались): \"{vacancy['vacancy_title']}\" — {vacancy['company_name']}")
                stats["skipped"] += 1
                continue

            success = await _respond_to_vacancy(page, vacancy)
            if success:
                database.save_response(vacancy)
                logger.info(f"✅ Отклик: \"{vacancy['vacancy_title']}\" — {vacancy['company_name']}")
                stats["sent"] += 1
                await human_delay.pause(
                    config.MIN_DELAY_BETWEEN_RESPONSES,
                    config.MAX_DELAY_BETWEEN_RESPONSES,
                )
            else:
                stats["errors"] += 1

    except Exception as e:
        logger.error(f"Критическая ошибка в run_responses: {e}")
        await save_error_screenshot(page, "vacancies_error")

    return stats


async def _search_vacancies(page) -> list[dict]:
    """Открыть страницу поиска и собрать список вакансий."""
    params = [
        ("text", config.VACANCY_SEARCH_TEXT),
        *[("search_field", f) for f in config.VACANCY_SEARCH_FIELD],
        ("items_on_page", str(config.VACANCY_ITEMS_ON_PAGE)),
        ("search_period", str(config.VACANCY_SEARCH_PERIOD)),
    ]

    url = "https://hh.ru/search/vacancy?" + urllib.parse.urlencode(params)

    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(2000)
    await human_delay.scroll_naturally(page)

    return await _parse_vacancy_list(page)


async def _parse_vacancy_list(page) -> list[dict]:
    """Извлечь данные вакансий со страницы результатов."""
    vacancies = []
    try:
        items = await page.query_selector_all("[data-qa='vacancy-serp__vacancy']")
        logger.info(f"Найдено элементов vacancy-serp__vacancy: {len(items)}")
        for item in items:
            try:
                vacancy = await _extract_vacancy_data(item)
                if vacancy:
                    vacancies.append(vacancy)
                else:
                    logger.debug("_extract_vacancy_data вернул None")
            except Exception as e:
                logger.debug(f"Ошибка парсинга вакансии: {e}")
    except Exception as e:
        logger.error(f"Ошибка получения списка вакансий: {e}")
    logger.info(f"Распарсено вакансий: {len(vacancies)}")
    return vacancies


async def _extract_vacancy_data(item) -> dict | None:
    """Извлечь данные одной вакансии через JS evaluate (надёжнее ElementHandle.query_selector)."""
    try:
        data = await item.evaluate("""el => {
            const titleEl = el.querySelector("[data-qa='serp-item__title']");
            const titleTextEl = el.querySelector("[data-qa='serp-item__title-text']");
            const companyEl = el.querySelector("[data-qa='vacancy-serp__vacancy-employer-text']")
                           || el.querySelector("[data-qa='vacancy-serp__vacancy-employer']");
            const salaryEl = el.querySelector("[data-qa='vacancy-serp__compensation']");
            const innerIdEl = el.querySelector('[id]');

            const url = titleEl
                ? (titleEl.tagName === 'A' ? titleEl.href : titleEl.closest('a')?.href || '')
                : '';
            const innerId = innerIdEl && /^\\d+$/.test(innerIdEl.id) ? innerIdEl.id : null;

            return {
                url: url || (innerId ? 'https://hh.ru/vacancy/' + innerId : null),
                title: (titleTextEl || titleEl)?.innerText?.trim() || null,
                company: companyEl?.innerText?.trim() || '',
                salary: salaryEl?.innerText?.trim() || '',
                innerId: innerId
            };
        }""")

        if not data or not data.get("url") or not data.get("title"):
            return None

        url = data["url"]
        vacancy_id = _extract_id_from_url(url) or data.get("innerId")
        if not vacancy_id:
            return None

        return {
            "vacancy_id": vacancy_id,
            "vacancy_title": data["title"],
            "company_name": data["company"],
            "vacancy_url": url if url.startswith("http") else f"https://hh.ru{url}",
            "salary_text": data["salary"],
        }
    except Exception as e:
        logger.debug(f"_extract_vacancy_data error: {e}")
        return None


def _extract_id_from_url(url: str) -> str | None:
    try:
        # URL вида /vacancy/12345678 или https://hh.ru/vacancy/12345678
        parts = url.rstrip("/").split("/")
        for part in reversed(parts):
            if part.isdigit():
                return part
        return None
    except Exception:
        return None


def _filter_vacancies(vacancies: list[dict]) -> list[dict]:
    """Отфильтровать вакансии по правилам из config."""
    result = []
    for v in vacancies:
        title_lower = v["vacancy_title"].lower()
        company_lower = v["company_name"].lower()

        # Черный список компаний
        if any(bl.lower() in company_lower for bl in config.COMPANIES_BLACKLIST):
            continue

        # Черный список по должности
        if any(kw.lower() in title_lower for kw in config.KEYWORDS_BLACKLIST):
            continue

        # Обязательные ключевые слова
        if config.KEYWORDS_REQUIRED:
            if not any(kw.lower() in title_lower for kw in config.KEYWORDS_REQUIRED):
                continue

        result.append(v)
    return result


async def _respond_to_vacancy(page, vacancy: dict) -> bool:
    """Открыть вакансию и откликнуться. Возвращает True при успехе."""
    context = page.context
    new_tab = await context.new_page()
    try:
        # Чистый URL без tracking-параметров
        clean_url = vacancy["vacancy_url"].split("?")[0]

        await new_tab.goto(clean_url, wait_until="domcontentloaded", timeout=60000)
        await new_tab.wait_for_timeout(2000)
        await human_delay.scroll_naturally(new_tab)

        # Нажать кнопку "Откликнуться"
        respond_btn = await new_tab.query_selector("[data-qa='vacancy-response-link-top']")
        if not respond_btn:
            respond_btn = await new_tab.query_selector("button[data-qa*='response']")
        if not respond_btn:
            respond_btn = await new_tab.query_selector("a[data-qa*='response']")
        if not respond_btn:
            logger.debug(f"Кнопка отклика не найдена: {clean_url}")
            return False

        await respond_btn.click(force=True, timeout=60000)
        await new_tab.wait_for_timeout(2000)

        # Модалка "Вы откликаетесь на вакансию в другой стране"
        cross_country_btn = await new_tab.query_selector("[data-qa='relocation-warning-confirm']")
        if not cross_country_btn:
            cross_country_btn = await new_tab.query_selector("button:has-text('Все равно откликнуться')")
        if cross_country_btn:
            logger.debug("Модалка 'другая страна' — подтверждаем")
            await cross_country_btn.click(force=True)
            await new_tab.wait_for_timeout(1500)

        # Если появилось поле сопроводительного письма
        cover_input = await new_tab.query_selector("[data-qa='vacancy-response-popup-form-letter-input']")
        if not cover_input:
            cover_input = await new_tab.query_selector("textarea[data-qa='vacancy-response-popup-letter']")
        if not cover_input:
            cover_input = await new_tab.query_selector("textarea[placeholder*='письм']")

        if cover_input:
            await cover_input.click(force=True)
            for char in config.COVER_LETTER_TEMPLATE:
                await cover_input.type(char, delay=random_char_delay())
            await asyncio.sleep(0.5)

        # Нажать "Отправить отклик"
        submit_btn = await new_tab.query_selector("[data-qa='vacancy-response-letter-submit']")
        if not submit_btn:
            submit_btn = await new_tab.query_selector("button[data-qa*='submit']")
        if not submit_btn:
            submit_btn = await new_tab.query_selector("button:has-text('Отправить')")
        if submit_btn:
            await submit_btn.click(force=True, timeout=60000)
            await new_tab.wait_for_timeout(2000)

        # Проверить подтверждение
        success = await _check_response_success(new_tab)
        return success

    except Exception as e:
        logger.error(f"Ошибка отклика на вакансию {vacancy['vacancy_url']}: {e}")
        await save_error_screenshot(new_tab, f"respond_error_{vacancy['vacancy_id']}")
        return False
    finally:
        await new_tab.close()


async def _check_response_success(page) -> bool:
    """Проверить, что отклик был отправлен успешно."""
    try:
        selectors = [
            "#dialog-description:has-text('Отклик отправлен')",
            "[data-qa='vacancy-response-success']",
            "text=Отклик отправлен",
            "text=Вы откликнулись",
        ]
        for sel in selectors:
            el = await page.query_selector(sel)
            if el:
                return True
        return False
    except Exception:
        return False


def random_char_delay() -> int:
    import random
    return random.randint(50, 200)
