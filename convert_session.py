"""
Конвертирует экспорт cookies (расширение Cookie-Editor / любое с похожим
JSON-форматом: name, value, domain, path, expirationDate, httpOnly, secure, sameSite)
в формат storage_state.json, который понимает Playwright.

Использование:
1. В браузере, где вы уже авторизованы на hh.ru, откройте Cookie-Editor
   -> Export -> Export as JSON. Скопируйте результат.
2. Сохраните скопированный JSON в файл raw_cookies.json рядом с этим скриптом
   (в корне проекта, там же где main.py и config.py).
3. Запустите: python convert_session.py
4. Результат появится в session/state.json — том же пути, что использует
   config.SESSION_PATH.
"""

import json
import os
import sys

RAW_COOKIES_FILE = "raw_cookies.json"
OUTPUT_FILE = os.path.join("session", "state.json")
DOMAIN_FILTER = "hh.ru"  # оставляем только куки этого домена


def convert_same_site(value):
    if not value:
        return "Lax"
    value = str(value).lower()
    if value in ("no_restriction", "none"):
        return "None"
    if value == "strict":
        return "Strict"
    return "Lax"


def convert_cookie(raw):
    expires = raw.get("expirationDate")
    if expires is None:
        expires = -1  # сессионная кука без явного срока
    return {
        "name": raw["name"],
        "value": raw["value"],
        "domain": raw.get("domain", ""),
        "path": raw.get("path", "/"),
        "expires": expires,
        "httpOnly": raw.get("httpOnly", False),
        "secure": raw.get("secure", False),
        "sameSite": convert_same_site(raw.get("sameSite")),
    }


def main():
    if not os.path.exists(RAW_COOKIES_FILE):
        print(f"Не найден файл {RAW_COOKIES_FILE}.")
        print("Экспортируйте cookies из браузера (Cookie-Editor -> Export as JSON) и сохраните их сюда.")
        sys.exit(1)

    with open(RAW_COOKIES_FILE, "r", encoding="utf-8") as f:
        raw_cookies = json.load(f)

    if not isinstance(raw_cookies, list):
        print("Ожидался JSON-массив cookies. Проверьте формат экспорта.")
        sys.exit(1)

    cookies = [
        convert_cookie(c) for c in raw_cookies
        if DOMAIN_FILTER in c.get("domain", "")
    ]

    if not cookies:
        print(f"Не найдено ни одной куки для домена '{DOMAIN_FILTER}'.")
        print("Убедитесь, что экспорт делался именно со страницы hh.ru.")
        sys.exit(1)

    storage_state = {
        "cookies": cookies,
        # Если авторизация на hh.ru завязана ещё и на localStorage —
        # добавьте сюда origins вручную, например:
        # "origins": [
        #     {
        #         "origin": "https://hh.ru",
        #         "localStorage": [{"name": "someKey", "value": "someValue"}]
        #     }
        # ]
        "origins": [],
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(storage_state, f, ensure_ascii=False, indent=2)

    print(f"Готово: сохранено {len(cookies)} cookies в {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
