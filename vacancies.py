import asyncio
import os
import itertools
import re
import urllib.parse
from datetime import date

import browser
import config
import database
import human_delay
from logger import LOG_DIR, logger, save_error_screenshot

# Профили поиска чередуются от прогона к прогону (см. config.SEARCH_PROFILES)
_profile_cycle = itertools.cycle(
    [p for p in config.SEARCH_PROFILES if p["name"] in config.ACTIVE_PROFILES]
)
_resume_id_cache: dict[str, str] = {}


async def _resolve_resume_id(page, title: str) -> str | None:
    """Найти id резюме по названию на странице /applicant/resumes."""
    if title in _resume_id_cache:
        return _resume_id_cache[title]
    await page.goto("https://hh.ru/applicant/resumes", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(2000)
    for block in await page.query_selector_all("[data-qa='resume']"):
        title_el = await block.query_selector("[data-qa='resume-title']")
        if not title_el or title.lower() not in (await title_el.inner_text()).lower():
            continue
        for a in await block.query_selector_all("a[href*='/resume/']"):
            m = re.search(r"/resume/([0-9a-f]{20,})", await a.get_attribute("href") or "")
            if m:
                _resume_id_cache[title] = m.group(1)
                return m.group(1)
    return None


def get_profile(name: str | None = None) -> dict:
    """Профиль по имени (для ручного запуска) или следующий по очереди."""
    if name is None:
        return next(_profile_cycle)
    for profile in config.SEARCH_PROFILES:
        if profile["name"] == name:
            return profile
    names = ", ".join(p["name"] for p in config.SEARCH_PROFILES)
    raise ValueError(f"Неизвестный профиль поиска '{name}'. Доступны: {names}")


async def run_responses(page, profile_name: str | None = None) -> dict:
    """
    Найти вакансии и откликнуться на подходящие.
    Возвращает {"sent": int, "skipped": int, "errors": int}
    """
    stats = {"sent": 0, "skipped": 0, "manual": 0, "errors": 0}
    profile = get_profile(profile_name)

    is_limited, blocked_until, block_reason = database.get_rate_limit_status()
    if is_limited:
        logger.info(f"Блокировка активна до {blocked_until} UTC ({block_reason}) — пропускаю прогон")
        return stats

    today_count = database.count_today_responses()
    if today_count >= config.DAILY_RESPONSE_CAP:
        logger.info(
            f"Дневной лимит откликов hh.ru достигнут ({today_count}/{config.DAILY_RESPONSE_CAP}) — жду завтра"
        )
        return stats

    logger.info(
        f"Запуск задачи: отклики на вакансии, профиль «{profile['name']}» "
        f"({today_count}/{config.DAILY_RESPONSE_CAP} за сегодня)"
    )

    try:
        vacancies = await _search_vacancies(page, profile)
        if not vacancies:
            logger.info("Вакансии не найдены")
            return stats

        filtered = _filter_vacancies(vacancies, profile)
        logger.info(f"Найдено {len(vacancies)} вакансий, после фильтрации: {len(filtered)}")

        for vacancy in filtered:
            if stats["sent"] >= config.MAX_RESPONSES_PER_RUN:
                logger.info(f"Лимит откликов за запуск достигнут ({stats['sent']}/{config.MAX_RESPONSES_PER_RUN})")
                break

            if database.is_already_responded(vacancy["vacancy_id"]):
                logger.warning(f"⏭  Пропуск (уже откликались): \"{vacancy['vacancy_title']}\" — {vacancy['company_name']}")
                stats["skipped"] += 1
                continue

            if database.is_in_manual_review(vacancy["vacancy_id"]):
                logger.warning(f"⏭  Пропуск (в списке на ручную обработку): \"{vacancy['vacancy_title']}\" — {vacancy['company_name']}")
                stats["skipped"] += 1
                continue

            result, reason = await _respond_to_vacancy(page, vacancy, profile)
            if result == "sent":
                database.save_response(vacancy)
                logger.info(f"✅ Отклик: \"{vacancy['vacancy_title']}\" — {vacancy['company_name']}")
                stats["sent"] += 1
                await human_delay.pause(
                    config.MIN_DELAY_BETWEEN_RESPONSES,
                    config.MAX_DELAY_BETWEEN_RESPONSES,
                )
            elif result == "limit_reached":
                minutes = config.CAPTCHA_BACKOFF_MINUTES if "капч" in (reason or "") else config.RATE_LIMIT_BACKOFF_MINUTES
                logger.warning(f"🛑 {reason} — останавливаю прогон, откладываю на {minutes} мин")
                database.set_rate_limited(minutes, reason)
                break
            elif result == "filtered":
                # Помечаем как обработанную, чтобы не открывать эту вакансию повторно
                database.save_manual_review(vacancy, reason)
                database.mark_manual_review_handled(vacancy["vacancy_id"])
                logger.info(f"⏭  Пропуск по описанию ({reason}): \"{vacancy['vacancy_title']}\" — {vacancy['company_name']}")
                stats["skipped"] += 1
                await human_delay.short_pause(4, 10)   # не листаем страницы вакансий подряд без пауз
            elif result == "manual":
                database.save_manual_review(vacancy, reason)
                logger.warning(f"✋ На ручную обработку (\"{reason}\"): \"{vacancy['vacancy_title']}\" — {vacancy['company_name']}")
                stats["manual"] += 1
            else:
                stats["errors"] += 1

    except Exception as e:
        logger.error(f"Критическая ошибка в run_responses: {e}")
        await save_error_screenshot(page, "vacancies_error")

    return stats


async def retry_manual_review(page, profile_name: str = "non_dev") -> dict:
    """
    Повторно прогнать вакансии из списка «На ручную обработку» (handled = 0).
    Отправленные уходят из списка в отклики, у остальных обновляется причина.
    """
    stats = {"sent": 0, "skipped": 0, "manual": 0, "errors": 0}
    profile = get_profile(profile_name)
    rows = database.get_unhandled_manual_review()
    logger.info(f"Повторный прогон ручных вакансий: {len(rows)} шт., профиль «{profile['name']}»")

    for vacancy in rows:
        title = f"\"{vacancy['vacancy_title']}\" — {vacancy['company_name']}"
        if database.is_already_responded(vacancy["vacancy_id"]):
            database.mark_manual_review_handled(vacancy["vacancy_id"])
            stats["skipped"] += 1
            continue

        result, reason = await _respond_to_vacancy(page, vacancy, profile)
        if result == "sent":
            database.save_response(vacancy)
            database.mark_manual_review_handled(vacancy["vacancy_id"])
            logger.info(f"✅ Отклик (из ручных): {title}")
            stats["sent"] += 1
            await human_delay.pause(config.MIN_DELAY_BETWEEN_RESPONSES, config.MAX_DELAY_BETWEEN_RESPONSES)
        elif result == "limit_reached":
            minutes = config.CAPTCHA_BACKOFF_MINUTES if "капч" in (reason or "") else config.RATE_LIMIT_BACKOFF_MINUTES
            logger.warning(f"🛑 {reason} — останавливаю повторный прогон, откладываю на {minutes} мин")
            database.set_rate_limited(minutes, reason)
            break
        elif result == "filtered":
            database.save_manual_review(vacancy, reason)
            database.mark_manual_review_handled(vacancy["vacancy_id"])
            logger.info(f"⏭  Пропуск по описанию ({reason}): {title}")
            stats["skipped"] += 1
            await human_delay.short_pause(4, 10)
        elif result == "manual":
            database.save_manual_review(vacancy, reason)
            logger.warning(f"✋ Осталась на ручной обработке (\"{reason}\"): {title}")
            stats["manual"] += 1
            await human_delay.short_pause(8, 20)
        else:
            logger.warning(f"⚠️ Ошибка, вакансия остаётся в ручных ({reason}): {title}")
            stats["errors"] += 1
            await human_delay.short_pause(8, 20)

    return stats


async def _search_vacancies(page, profile: dict) -> list[dict]:
    """Открыть страницу поиска и собрать список вакансий по всем страницам выдачи."""
    all_vacancies: list[dict] = []
    seen_ids: set[str] = set()

    recommended_title = profile.get("recommended_for_resume")
    resume_param: dict[str, str] = {}
    if recommended_title:
        resume_id = profile.get("resume_id") or await _resolve_resume_id(page, recommended_title)
        if not resume_id:
            logger.error(f"Не нашёл резюме «{recommended_title}» на hh.ru — рекомендации недоступны")
            return []
        resume_param = {"resume": resume_id}

    for page_num in range(profile["max_pages"]):
        params = {
            "items_on_page": str(config.VACANCY_ITEMS_ON_PAGE),
            "page": str(page_num),
            **resume_param,
        }
        if not recommended_title:   # рекомендации hh.ru сам ограничивает по свежести
            params["text"] = profile["search_text"]
            params["search_period"] = str(config.VACANCY_SEARCH_PERIOD)
        params.update(profile["extra_params"])      # work_format, order_by, свой search_period
        params = [
            *params.items(),
            *[("search_field", f) for f in profile["search_field"]],
        ]
        url = "https://hh.ru/search/vacancy?" + urllib.parse.urlencode(params)

        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)

        if await browser.is_ddos_challenge(page):
            reason = "DDoS-Guard проверка браузера на странице поиска"
            logger.warning(f"{reason} — откладываю попытки")
            database.set_rate_limited(config.RATE_LIMIT_BACKOFF_MINUTES, reason)
            break

        await human_delay.scroll_naturally(page)

        page_vacancies = await _parse_vacancy_list(page)
        new_on_page = 0
        for v in page_vacancies:
            if v["vacancy_id"] not in seen_ids:
                seen_ids.add(v["vacancy_id"])
                all_vacancies.append(v)
                new_on_page += 1

        if len(page_vacancies) < config.VACANCY_ITEMS_ON_PAGE or new_on_page == 0:
            # Последняя страница выдачи или дальше идут дубликаты
            break

        await human_delay.short_pause(2, 5)

    return all_vacancies


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
            const innerIdEl = el.querySelector('[id]');

            const url = titleEl
                ? (titleEl.tagName === 'A' ? titleEl.href : titleEl.closest('a')?.href || '')
                : '';
            const innerId = innerIdEl && /^\\d+$/.test(innerIdEl.id) ? innerIdEl.id : null;

            // Зарплата в новой вёрстке hh.ru (Magritte) не имеет data-qa —
            // ищем текстовый узел с валютой и берём текст его родителя
            let salary = '';
            const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
            let node;
            while (node = walker.nextNode()) {
                if (/[₸₽$€]/.test(node.textContent)) {
                    salary = node.parentElement.innerText.replace(/[\\s\\u00a0\\u202f]+/g, ' ').trim();
                    break;
                }
            }

            return {
                url: url || (innerId ? 'https://hh.ru/vacancy/' + innerId : null),
                title: (titleTextEl || titleEl)?.innerText?.trim() || null,
                company: companyEl?.innerText?.trim() || '',
                salary: salary,
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


def _title_has_keyword(title_lower: str, keyword: str, word_start: bool) -> bool:
    kw = keyword.lower()
    if not word_start:
        return kw in title_lower
    # Слово должно начинаться с kw: «qa» найдёт «QA-инженер», но не «aqua»
    return re.search(rf"(?<!\w){re.escape(kw)}", title_lower) is not None


def _filter_vacancies(vacancies: list[dict], profile: dict) -> list[dict]:
    """Отфильтровать вакансии по правилам из config и профиля поиска."""
    result = []
    dropped_by_whitelist: list[str] = []
    for v in vacancies:
        title_lower = v["vacancy_title"].lower()
        company_lower = v["company_name"].lower()

        # Черный список компаний
        if any(bl.lower() in company_lower for bl in config.COMPANIES_BLACKLIST):
            continue

        # Черный список по должности (свой у каждого профиля)
        if any(
            _title_has_keyword(title_lower, kw, profile["title_word_start"])
            for kw in profile["title_blacklist"]
        ):
            continue

        # Белый список по должности (если задан в профиле): название должно содержать любое слово
        whitelist = profile.get("title_whitelist")
        if whitelist and not any(_title_has_keyword(title_lower, kw, True) for kw in whitelist):
            dropped_by_whitelist.append(v["vacancy_title"])
            continue

        # Обязательные ключевые слова
        if config.KEYWORDS_REQUIRED:
            if not any(kw.lower() in title_lower for kw in config.KEYWORDS_REQUIRED):
                continue

        result.append(v)
    if dropped_by_whitelist:
        sample = "; ".join(dropped_by_whitelist[:15])
        logger.info(f"Не прошли белый список названий: {len(dropped_by_whitelist)}, например: {sample}")
    return result


async def _select_resume(tab, resume_title: str) -> bool:
    """
    Если у аккаунта несколько резюме, в окне отклика есть карточка-выпадашка с выбранным резюме.
    True — в карточке выбрано нужное резюме и список закрыт (кнопки окна не перекрыты).
    """
    try:
        card = tab.locator("[role='button']:has([data-qa='resume-title'])").first
        await card.wait_for(state="visible", timeout=5000)
        current = card.locator("[data-qa='resume-title']").first
        wanted = resume_title.lower()

        # hh.ru запоминает последнее использованное резюме: если нужное уже выбрано —
        # ничего не трогаем. Лишний клик раскрывает список, и он перекрывает кнопку «Откликнуться».
        if wanted in (await current.inner_text()).lower():
            return True

        await card.click(timeout=5000)
        option = tab.locator("[role='option']").filter(has_text=resume_title).first
        await option.click(timeout=5000)

        listbox = tab.locator("[role='listbox']")
        for _ in range(10):
            await tab.wait_for_timeout(300)
            if wanted in (await current.inner_text()).lower() and not await listbox.count():
                return True
        logger.debug(f"_select_resume: резюме «{resume_title}» не выбралось или список не закрылся")
        return False
    except Exception as e:
        logger.debug(f"_select_resume: не нашёл резюме «{resume_title}»: {e}")
        return False


async def _respond_to_vacancy(page, vacancy: dict, profile: dict) -> tuple[str, str | None]:
    """
    Открыть вакансию и откликнуться.
    Возвращает (status, reason), где status одно из:
      "sent"          — отклик подтверждён
      "manual"        — бот не смог довести отклик до конца, нужна ручная обработка (reason заполнен)
      "error"         — техническая ошибка (таймаут, исключение)
      "limit_reached" — hh.ru сообщил об исчерпании дневного лимита откликов
    """
    context = page.context
    new_tab = await context.new_page()
    try:
        # Чистый URL без tracking-параметров
        clean_url = vacancy["vacancy_url"].split("?")[0]

        await new_tab.goto(clean_url, wait_until="domcontentloaded", timeout=60000)
        await new_tab.wait_for_timeout(2000)

        if await browser.is_ddos_challenge(new_tab):
            # Не считаем это сразу поводом для ручной обработки или блокировки всего
            # прогона — часто это разовая помеха. Ждём и пробуем эту же вакансию ещё раз.
            logger.warning(f"DDoS-Guard проверка браузера, повторю попытку: {clean_url}")
            await human_delay.pause(config.MIN_DELAY_BETWEEN_RESPONSES, config.MAX_DELAY_BETWEEN_RESPONSES)
            await new_tab.goto(clean_url, wait_until="domcontentloaded", timeout=60000)
            await new_tab.wait_for_timeout(2000)

            if await browser.is_ddos_challenge(new_tab):
                reason = "DDoS-Guard проверка браузера — не прошла и со второй попытки"
                logger.warning(f"{reason}: {clean_url}")
                await _save_review_screenshot(new_tab, vacancy["vacancy_id"], "ddos_guard")
                return "manual", reason

            logger.debug("DDoS-Guard прошла со второй попытки, продолжаю")

        await human_delay.scroll_naturally(new_tab)

        # Отсев по описанию (профиль задаёт description_blacklist): строгий контроль присутствия, смены, продажи
        flags = profile.get("description_blacklist")
        if flags:
            desc_el = await new_tab.query_selector("[data-qa='vacancy-description']")
            desc = ((await desc_el.inner_text()) if desc_el else "").lower()
            hit = next((f for f in flags if f in desc), None)
            if hit:
                return "filtered", f"В описании «{hit}»"

        # Уже откликались (например, вручную на сайте) — повторно не отправляем
        if await new_tab.query_selector("text=Вы откликнулись"):
            logger.debug(f"На странице уже отмечен отклик: {clean_url}")
            return "sent", None

        # Нажать кнопку "Откликнуться"
        respond_btn = await new_tab.query_selector("[data-qa='vacancy-response-link-top']")
        if not respond_btn:
            respond_btn = await new_tab.query_selector("button[data-qa*='response']")
        if not respond_btn:
            respond_btn = await new_tab.query_selector("a[data-qa*='response']")
        if not respond_btn:
            reason = "Нет кнопки 'Откликнуться' на странице вакансии"
            logger.warning(f"{reason}: {clean_url}")
            await _save_review_screenshot(new_tab, vacancy["vacancy_id"], "no_button")
            return "manual", reason

        await respond_btn.click(force=True, timeout=60000)
        await new_tab.wait_for_timeout(2000)

        # hh.ru показывает тост "Вы исчерпали лимит откликов" при достижении
        # реального лимита (200 за скользящие 24 часа); тост иногда всплывает
        # с задержкой, поэтому эта же проверка повторяется ниже по функции
        if await _check_rate_limited(new_tab):
            reason = "hh.ru: лимит откликов исчерпан (не более 200 за 24 часа)"
            logger.warning(f"{reason}: {clean_url}")
            await _save_review_screenshot(new_tab, vacancy["vacancy_id"], "rate_limit")
            return "limit_reached", reason

        # Модалка "Вы откликаетесь на вакансию в другой стране" — рендерится асинхронно
        # и может появиться позже фиксированной паузы выше, поэтому здесь именно
        # ожидание появления (wait_for_selector), а не мгновенная проверка
        cross_country_btn = None
        for sel in ["[data-qa='relocation-warning-confirm']", "button:has-text('Все равно откликнуться')"]:
            try:
                cross_country_btn = await new_tab.wait_for_selector(sel, timeout=3000, state="visible")
                break
            except Exception:
                continue
        if cross_country_btn:
            logger.debug("Модалка 'другая страна' — подтверждаем")
            await cross_country_btn.click(force=True)
            await new_tab.wait_for_timeout(1500)

        # На части вакансий hh.ru отправляет отклик мгновенно по первому клику
        # (без формы сопроводительного письма) и сразу открывает чат с работодателем.
        # Если это произошло — выходим сейчас же, не трогая текстовые поля на странице
        # (иначе шаблон письма уйдёт как сообщение в уже открывшийся чат).
        if await _check_response_success(new_tab):
            if profile["resume_title"]:
                logger.warning(
                    f"Отклик ушёл мгновенно, без выбора резюме «{profile['resume_title']}» — "
                    f"проверьте, какое резюме использовано: {clean_url}"
                )
            logger.debug("Отклик отправлен мгновенно (без формы письма)")
            return "sent", None

        # Профиль привязан к конкретному резюме — выбираем его. Если выбрать не удалось,
        # не отправляем (иначе уйдёт не то резюме) и отдаём вакансию на ручную обработку.
        if profile["resume_title"] and not await _select_resume(new_tab, profile["resume_title"]):
            reason = f"Не удалось выбрать резюме «{profile['resume_title']}» в окне отклика"
            logger.warning(f"{reason}: {clean_url}")
            await _save_review_screenshot(new_tab, vacancy["vacancy_id"], "no_resume_choice")
            return "manual", reason

        # Анкета работодателя (вопросы с полями «Писать тут» / Да-Нет): бот её не заполняет.
        # Проверяем до нажатия отправки — иначе submit по пустой форме только подсвечивает
        # обязательные поля красным, а вакансия уходит в ручные с непонятной причиной.
        if await _has_employer_questionnaire(new_tab):
            reason = "Анкета работодателя: нужны ответы на вопросы (бот их не заполняет)"
            logger.warning(f"{reason}: {clean_url}")
            await _save_review_screenshot(new_tab, vacancy["vacancy_id"], "questionnaire")
            return "manual", reason

        # В новом окне отклика поле письма скрыто за кнопкой «Добавить сопроводительное»
        add_letter_btn = await new_tab.query_selector("[data-qa='add-cover-letter']")
        if add_letter_btn:
            await add_letter_btn.click(timeout=5000)
            await new_tab.wait_for_timeout(700)

        # Если появилось поле сопроводительного письма
        cover_input = await new_tab.query_selector("[data-qa='vacancy-response-popup-form-letter-input']")
        if not cover_input:
            cover_input = await new_tab.query_selector("textarea[data-qa='vacancy-response-popup-letter']")
        if not cover_input:
            cover_input = await new_tab.query_selector("textarea[placeholder*='письм']")

        if cover_input:
            # Тост о лимите иногда всплывает уже к этому моменту — если печатать
            # в уже неактуальное поле, это может подвесить посимвольный ввод
            if await _check_rate_limited(new_tab):
                reason = "hh.ru: лимит откликов исчерпан (не более 200 за 24 часа)"
                logger.warning(f"{reason}: {clean_url}")
                await _save_review_screenshot(new_tab, vacancy["vacancy_id"], "rate_limit")
                return "limit_reached", reason

            await cover_input.click(force=True)
            for char in profile["cover_letter"]:
                await cover_input.type(char, delay=random_char_delay())
            await asyncio.sleep(0.5)

        # Нажать "Отправить отклик"
        submit_btn = await new_tab.query_selector("[data-qa='vacancy-response-submit-popup']")
        if not submit_btn:
            submit_btn = await new_tab.query_selector("[data-qa='vacancy-response-letter-submit']")
        if not submit_btn:
            submit_btn = await new_tab.query_selector("button[data-qa*='submit']")
        if not submit_btn:
            submit_btn = await new_tab.query_selector("button:has-text('Отправить')")

        if not submit_btn:
            # Тост о лимите иногда всплывает с задержкой — проверяем ещё раз
            # перед тем как решить, что это просто незнакомая форма
            if await _check_rate_limited(new_tab):
                reason = "hh.ru: лимит откликов исчерпан (не более 200 за 24 часа)"
                logger.warning(f"{reason}: {clean_url}")
                await _save_review_screenshot(new_tab, vacancy["vacancy_id"], "rate_limit")
                return "limit_reached", reason

            # Кнопка отклика была, но дальше — незнакомая форма/модалка
            # (например, тест или вопросы работодателя), которую бот не умеет заполнять
            reason = "После клика 'Откликнуться' появилась незнакомая форма без кнопки отправки"
            logger.warning(f"{reason}: {clean_url}")
            await _save_review_screenshot(new_tab, vacancy["vacancy_id"], "no_submit")
            return "manual", reason

        # Без force: если кнопку что-то перекрывает, клик упадёт с ошибкой (вакансия уйдёт
        # на повтор в следующем прогоне), а не попадёт молча в перекрывающий элемент
        await submit_btn.click(timeout=15000)

        # Исход появляется не мгновенно (подтверждение, анкета, капча) — ждём его, а не фиксированную паузу
        for _ in range(20):
            await new_tab.wait_for_timeout(500)

            if await _check_response_success(new_tab):
                return "sent", None

            if await _check_rate_limited(new_tab):
                reason = "hh.ru: лимит откликов исчерпан (не более 200 за 24 часа)"
                logger.warning(f"{reason}: {clean_url}")
                await _save_review_screenshot(new_tab, vacancy["vacancy_id"], "rate_limit")
                return "limit_reached", reason

            # hh.ru требует капчу — это признак подозрения на автоматизацию: не решаем её и не долбим сайт,
            # а откладываем попытки (вакансия не попадает в ручную обработку, она ещё не отправлена)
            if await new_tab.query_selector("text=Пройдите капчу"):
                reason = "hh.ru просит капчу"
                logger.warning(f"{reason}: {clean_url}")
                await _save_review_screenshot(new_tab, vacancy["vacancy_id"], "captcha")
                return "limit_reached", reason

            if await _has_employer_questionnaire(new_tab):
                reason = "Анкета работодателя: нужны ответы на вопросы (бот их не заполняет)"
                logger.warning(f"{reason}: {clean_url}")
                await _save_review_screenshot(new_tab, vacancy["vacancy_id"], "questionnaire")
                return "manual", reason

        reason = "Кнопка отправки нажата, но подтверждение отклика не найдено"
        logger.warning(f"{reason}: {clean_url}")
        await _save_review_screenshot(new_tab, vacancy["vacancy_id"], "no_confirmation")
        await _save_review_html(new_tab, vacancy["vacancy_id"], "no_confirmation")
        return "manual", reason

    except Exception as e:
        logger.error(f"Ошибка отклика на вакансию {vacancy['vacancy_url']}: {e}")
        await save_error_screenshot(new_tab, f"respond_error_{vacancy['vacancy_id']}")
        return "error", str(e)
    finally:
        await new_tab.close()


async def _save_review_screenshot(page, vacancy_id: str, tag: str) -> None:
    await save_error_screenshot(page, f"manual_review_{tag}_{vacancy_id}")


async def _save_review_html(page, vacancy_id: str, tag: str) -> None:
    """HTML страницы рядом со скриншотом — чтобы непонятный случай можно было разобрать по DOM."""
    try:
        path = os.path.join(LOG_DIR, "screenshots", f"manual_review_{tag}_{vacancy_id}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(await page.content())
        logger.debug(f"HTML сохранён: {path}")
    except Exception as e:
        logger.debug(f"_save_review_html: не удалось сохранить HTML: {e}")


async def _has_employer_questionnaire(page) -> bool:
    """
    Есть ли в окне отклика анкета работодателя. В новой вёрстке hh.ru подсказка «Писать тут»
    рисуется отдельным элементом, а не атрибутом placeholder, поэтому проверяем и текст,
    и сам атрибут, и любые textarea, кроме поля сопроводительного письма.
    """
    selectors = [
        "text=Писать тут",
        "textarea[placeholder='Писать тут']",
    ]
    for sel in selectors:
        try:
            if await page.query_selector(sel):
                return True
        except Exception:
            continue
    try:
        for ta in await page.query_selector_all("textarea"):
            qa = (await ta.get_attribute("data-qa")) or ""
            placeholder = (await ta.get_attribute("placeholder")) or ""
            if "letter" in qa or "письм" in placeholder.lower():
                continue
            if await ta.is_visible():
                return True
    except Exception:
        pass
    return False


async def _check_rate_limited(page) -> bool:
    """Проверить тост hh.ru об исчерпании лимита откликов (200 за 24 часа)."""
    try:
        return await page.query_selector("text=исчерпали лимит откликов") is not None
    except Exception:
        return False


async def _check_response_success(page) -> bool:
    """Проверить, что отклик был отправлен успешно."""
    try:
        selectors = [
            "#dialog-description:has-text('Отклик отправлен')",
            "[data-qa='vacancy-response-success']",
            "[data-qa='vacancy-response-success-standard-notification']",
            "text=Отклик отправлен",
            "text=Вы откликнулись",
            "text=Резюме доставлено",
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
