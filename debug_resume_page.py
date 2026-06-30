"""
Диагностический скрипт: открывает страницу резюме, делает скриншот и дампит HTML.
Запуск: python debug_resume_page.py
"""
import asyncio
import os
import datetime

import browser
import config


async def main():
    await browser.start_playwright()
    _, ctx = await browser.load_session()
    page = await ctx.new_page()

    print("Открываю страницу резюме...")
    await page.goto("https://hh.ru/applicant/resumes", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    print(f"URL: {page.url}")

    # Скриншот
    log_dir = os.path.join(os.path.dirname(__file__), "logs", "screenshots")
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    shot_path = os.path.join(log_dir, f"debug_resume_{ts}.png")
    await page.screenshot(path=shot_path, full_page=True)
    print(f"Скриншот сохранён: {shot_path}")

    # Дамп HTML
    html = await page.content()
    html_path = os.path.join(log_dir, f"debug_resume_{ts}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML сохранён: {html_path}")

    # Проверяем различные селекторы
    selectors_to_try = [
        "[data-qa='resume-block']",
        "[data-qa='resume-list-item']",
        "[data-qa='resume-card']",
        "[data-qa='resume']",
        "a[data-qa='resume-title']",
        "[class*='resumeCard']",
        "[class*='resume-card']",
        "[class*='resume-list']",
        "[class*='ResumeCard']",
        "[class*='resume_list']",
        "article",
        ".resume",
    ]

    print("\n--- Проверка селекторов ---")
    for sel in selectors_to_try:
        try:
            elements = await page.query_selector_all(sel)
            if elements:
                print(f"  НАЙДЕНО {len(elements):2d}  {sel}")
            else:
                print(f"  пусто        {sel}")
        except Exception as e:
            print(f"  ОШИБКА: {e}  {sel}")

    # Ищем все data-qa атрибуты на странице
    print("\n--- data-qa атрибуты на странице (уникальные) ---")
    data_qa_vals = await page.evaluate("""() => {
        const els = document.querySelectorAll('[data-qa]');
        const vals = [...new Set([...els].map(e => e.getAttribute('data-qa')))];
        return vals.sort();
    }""")
    for v in data_qa_vals:
        print(f"  {v}")

    await browser.stop_playwright()
    print("\nГотово. Посмотрите скриншот и список data-qa атрибутов выше.")


if __name__ == "__main__":
    asyncio.run(main())
