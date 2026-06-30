"""Диагностика: проверяем реальные селекторы на странице поиска вакансий."""
import asyncio
import os
import datetime
import urllib.parse

import browser
import config


async def main():
    await browser.start_playwright()
    _, ctx = await browser.load_session()
    page = await ctx.new_page()

    params = [
        ("text", config.VACANCY_SEARCH_TEXT),
        *[("search_field", f) for f in config.VACANCY_SEARCH_FIELD],
        ("items_on_page", str(config.VACANCY_ITEMS_ON_PAGE)),
        ("search_period", str(config.VACANCY_SEARCH_PERIOD)),
    ]
    url = "https://hh.ru/search/vacancy?" + urllib.parse.urlencode(params)

    print(f"URL: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)
    print(f"Финальный URL: {page.url}")

    # Скриншот
    log_dir = os.path.join(os.path.dirname(__file__), "logs", "screenshots")
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    await page.screenshot(path=os.path.join(log_dir, f"debug_vacancies_{ts}.png"), full_page=True)
    print(f"Скриншот: logs/screenshots/debug_vacancies_{ts}.png")

    selectors_to_try = [
        "[data-qa='vacancy-serp__vacancy']",
        "[data-qa='serp-item']",
        "[data-qa='vacancy-serp-item']",
        "[data-qa='vacancy-card']",
        "[class*='vacancyCard']",
        "[class*='vacancy-card']",
        "[class*='serp-item']",
        "li[class*='vacancy']",
        ".vacancy-serp-item",
    ]

    print("\n--- Проверка селекторов ---")
    for sel in selectors_to_try:
        try:
            els = await page.query_selector_all(sel)
            print(f"  {'НАЙДЕНО ' + str(len(els)):12}  {sel}")
        except Exception as e:
            print(f"  ОШИБКА: {e}  {sel}")

    # Инспекция первого vacancy элемента
    first = await page.query_selector("[data-qa='vacancy-serp__vacancy']")
    if first:
        print("\n--- data-qa внутри первого vacancy-serp__vacancy ---")
        inner_vals = await first.evaluate("""el => {
            const els = el.querySelectorAll('[data-qa]');
            return [...new Set([...els].map(e => e.getAttribute('data-qa')))].sort();
        }""")
        for v in inner_vals:
            print(f"  {v}")

        print("\n--- outerHTML первого vacancy (первые 2000 символов) ---")
        html = await first.evaluate("el => el.outerHTML")
        print(html[:2000])

    await browser.stop_playwright()


if __name__ == "__main__":
    asyncio.run(main())
