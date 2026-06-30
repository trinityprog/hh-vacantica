# ТЗ: HH.ru Job Assistant — MVP v2
# (Playwright + браузерная автоматизация)

## Контекст: почему не перехват запросов

С 15 декабря 2025 года HH.ru закрыл публичный API для соискателей.
Перехват HTTP-запросов (requests/httpx) отклоняется WAF: анализ TLS-отпечатков,
поведенческая биометрия и JS-антибот детектируют скрипты за несколько минут.

**Рабочий подход в 2026 году — Playwright с реальным браузером (не headless).**
Для HH.ru это выглядит как обычная пользовательская сессия.
Запускается локально на твоём компьютере — никакого сервера не нужно.

---

## Архитектура MVP

```
hh_job_assistant/
├── main.py               # Точка входа, запуск планировщика
├── config.py             # Все настройки (фильтры, расписание, письмо)
├── browser.py            # Инициализация Playwright, управление сессией
├── resume.py             # Модуль поднятия резюме
├── vacancies.py          # Модуль поиска и откликов
├── database.py           # SQLite — история откликов
├── human_delay.py        # Случайные задержки (мимикрия под человека)
├── logger.py             # Логирование всех действий
├── session/              # Папка для хранения браузерного состояния (cookies)
│   └── .gitkeep
├── logs/                 # Логи
│   └── .gitkeep
├── .env                  # Логин/пароль HH (локально, не коммитить)
└── requirements.txt
```

---

## Авторизация (browser.py)

### Метод: сохранение браузерной сессии

Playwright умеет сохранять полное состояние браузера (cookies + localStorage)
в файл. После первого входа вручную — последующие запуски не требуют логина.

### Первый запуск (ручной вход)

```
python main.py --login
```

1. Открывается реальный браузер Chrome
2. Пользователь вводит логин/пароль вручную (можно через телефон/Яндекс ID)
3. После успешного входа — скрипт сохраняет сессию в `session/state.json`
4. Браузер закрывается
5. Все следующие запуски используют сохранённую сессию — вход не нужен

### Управление сессией

```python
# browser.py — ключевые функции

async def save_session(page):
    """Сохранить состояние браузера после входа"""
    await page.context.storage_state(path="session/state.json")

async def load_session(playwright):
    """Загрузить сохранённую сессию"""
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context(storage_state="session/state.json")
    return browser, context

async def is_logged_in(page) -> bool:
    """Проверить, активна ли сессия"""
    await page.goto("https://hh.ru/applicant/resumes")
    return "login" not in page.url
```

### Хранение учётных данных (только для --login режима)

```
# .env
HH_LOGIN=your@email.com
HH_PASSWORD=yourpassword   # используется только при --login, не хранится в сессии
```

---

## Модуль 1: Поднятие резюме (resume.py)

### Логика

HH.ru позволяет поднимать резюме раз в 4 часа через кнопку "Поднять в поиске"
на странице `/applicant/resumes`.

### Алгоритм

```
1. Открыть страницу https://hh.ru/applicant/resumes
2. Найти нужное резюме (по названию из config.RESUME_TITLE)
3. Проверить наличие кнопки "Поднять в поиске"
   - Кнопка активна → нажать, подождать подтверждения → залогировать успех
   - Кнопки нет / она неактивна → залогировать "ещё не время", пропустить
4. Сделать скриншот результата (для отладки)
```

### Расписание (APScheduler, московское время)

| Время | Причина |
|-------|---------|
| 09:00 | Утренний старт рекрутеров |
| 12:00 | Обеденный просмотр |
| 17:00 | Конец рабочего дня |
| 21:00 | Вечерний просмотр |

```python
# config.py
RESUME_TITLE = "Python разработчик"    # Название резюме на HH (как на сайте)
RESUME_SCHEDULE_TIMES = ["09:00", "12:00", "17:00", "21:00"]
TIMEZONE = "Asia/Almaty"               # Или "Europe/Moscow"
```

### Функция

```python
async def publish_resume(page) -> dict:
    """
    Поднять резюме.
    Возвращает: {"success": bool, "message": str}
    """
```

---

## Модуль 2: Авто-отклики (vacancies.py)

### Шаг 1: Поиск вакансий

Открываем страницу поиска с параметрами из config.py:

```
URL: https://hh.ru/search/vacancy?text=Python+разработчик&area=2&salary=200000&...
```

Playwright парсит список вакансий со страницы результатов поиска.

### Шаг 2: Фильтрация

Для каждой найденной вакансии проверяем:

```python
# Фильтры в config.py
VACANCY_SEARCH_TEXT = "Python разработчик"
VACANCY_AREA = 2                            # 2 = Алматы, 1 = Москва
SALARY_MIN = 0                              # 0 = не фильтровать
KEYWORDS_REQUIRED = ["Python"]             # Хотя бы одно из списка в названии/тексте
KEYWORDS_BLACKLIST = ["стажёр", "intern", "junior"]
COMPANIES_BLACKLIST = []
MAX_RESPONSES_PER_RUN = 5                  # Лимит за один запуск
ONLY_NEW_VACANCIES = True                  # Только вакансии, опубликованные сегодня
```

Логика фильтра (все условия обязательны):
1. Вакансия не в SQLite (ещё не откликались)
2. Зарплата >= SALARY_MIN (если указана)
3. В названии есть слово из KEYWORDS_REQUIRED
4. В названии нет слов из KEYWORDS_BLACKLIST
5. Компания не в COMPANIES_BLACKLIST
6. За текущий запуск отправлено < MAX_RESPONSES_PER_RUN

### Шаг 3: Отклик

```
Для каждой подходящей вакансии:
1. Открыть страницу вакансии в новой вкладке
2. Нажать кнопку "Откликнуться"
3. Если появилось поле сопроводительного письма → вставить COVER_LETTER_TEMPLATE
4. Нажать "Отправить отклик"
5. Дождаться подтверждения ("Отклик отправлен")
6. Сохранить в БД
7. Закрыть вкладку
8. human_delay.pause()   ← случайная пауза 10-30 секунд между откликами
```

### Расписание откликов

| Время | Действие |
|-------|----------|
| 09:05 | Поиск + отклики (после поднятия резюме) |
| 17:05 | Поиск + отклики |

---

## Мимикрия под человека (human_delay.py)

Это критически важный модуль. Без случайных задержек HH обнаружит бота.

```python
import random
import asyncio

async def pause(min_sec=8, max_sec=25):
    """Случайная пауза между действиями"""
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)

async def typing_delay():
    """Пауза при вводе текста — как живой человек"""
    await asyncio.sleep(random.uniform(0.05, 0.2))

async def scroll_naturally(page):
    """Медленный скролл страницы перед кликом"""
    for _ in range(random.randint(2, 5)):
        await page.mouse.wheel(0, random.randint(100, 400))
        await asyncio.sleep(random.uniform(0.3, 1.2))
```

**Правила безопасности:**
- Между откликами: 10–30 секунд (случайно)
- Между страницами: 3–8 секунд
- Максимум 5 откликов за один запуск
- Не запускать ночью (только 09:00–21:00)
- Не запускать каждые несколько минут

---

## База данных (database.py)

### Таблица `responses`

```sql
CREATE TABLE IF NOT EXISTS responses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id      TEXT NOT NULL UNIQUE,
    vacancy_title   TEXT,
    company_name    TEXT,
    vacancy_url     TEXT,
    salary_text     TEXT,
    responded_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    status          TEXT DEFAULT 'sent'
);
```

### Таблица `resume_publishes`

```sql
CREATE TABLE IF NOT EXISTS resume_publishes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    published_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    success      INTEGER,
    message      TEXT
);
```

### Функции

```python
def is_already_responded(vacancy_id: str) -> bool
def save_response(vacancy: dict) -> None
def save_publish(success: bool, message: str) -> None
def get_stats() -> dict   # для логов: всего откликов, сегодня, поднятий
```

---

## Логирование (logger.py)

```
[2026-06-29 09:00:01] INFO    Запуск задачи: поднятие резюме
[2026-06-29 09:00:04] INFO    ✅ Резюме поднято: "Python разработчик"
[2026-06-29 09:05:01] INFO    Запуск задачи: отклики на вакансии
[2026-06-29 09:05:08] INFO    Найдено 18 вакансий, после фильтрации: 4
[2026-06-29 09:05:21] INFO    ✅ Отклик: "Senior Python Dev" — ТОО TechAlmaty
[2026-06-29 09:05:47] INFO    ✅ Отклик: "Backend Python" — ООО Fintech
[2026-06-29 09:05:49] WARNING ⏭  Пропуск (уже откликались): "Django Dev" — Acme
[2026-06-29 09:06:15] INFO    ✅ Отклик: "Python/FastAPI" — KZ Digital
[2026-06-29 09:06:16] INFO    Лимит откликов за запуск достигнут (3/5)
[2026-06-29 12:00:01] WARNING ⏳ Резюме ещё нельзя поднять (прошло < 4 часов)
```

- Файл: `logs/app.log`
- Вывод также в консоль
- Ротация: 7 файлов по 5 МБ
- Скриншоты ошибок: `logs/screenshots/`

---

## Точка входа (main.py)

```python
# Режимы запуска:

# 1. Первый вход (только один раз):
python main.py --login

# 2. Тест поднятия резюме прямо сейчас:
python main.py --now-publish

# 3. Тест откликов прямо сейчас:
python main.py --now-respond

# 4. Основной режим — планировщик работает непрерывно:
python main.py

# При Ctrl+C — корректное завершение с закрытием браузера
```

---

## config.py — полная структура

```python
import os
from dotenv import load_dotenv
load_dotenv()

# --- Авторизация ---
HH_LOGIN = os.getenv("HH_LOGIN")
HH_PASSWORD = os.getenv("HH_PASSWORD")      # только для --login режима

# --- Резюме ---
RESUME_TITLE = "Python разработчик"          # Название резюме на HH (точное совпадение)
RESUME_SCHEDULE_TIMES = ["09:00", "12:00", "17:00", "21:00"]
TIMEZONE = "Asia/Almaty"

# --- Поиск вакансий ---
VACANCY_SEARCH_TEXT = "Python разработчик"
VACANCY_AREA = 2                             # 2 = Алматы
VACANCY_SCHEDULE_TIMES = ["09:05", "17:05"]
ONLY_NEW_VACANCIES = True                    # Только сегодняшние вакансии

# --- Фильтры ---
SALARY_MIN = 0
KEYWORDS_REQUIRED = ["Python"]
KEYWORDS_BLACKLIST = ["стажёр", "intern", "junior", "trainee"]
COMPANIES_BLACKLIST = []
MAX_RESPONSES_PER_RUN = 5

# --- Безопасность ---
MIN_DELAY_BETWEEN_RESPONSES = 10            # секунд (минимум)
MAX_DELAY_BETWEEN_RESPONSES = 30            # секунд (максимум)

# --- Сопроводительное письмо ---
COVER_LETTER_TEMPLATE = """
Добрый день!

Откликаюсь на вашу вакансию. Имею опыт разработки на Python,
готов обсудить детали.

С уважением
"""
```

---

## requirements.txt

```
playwright==1.44.0
APScheduler==3.10.4
python-dotenv==1.0.0
```

После установки: `playwright install chromium`

---

## Ограничения HH.ru (важно соблюдать)

| Ограничение | Значение | Как учитываем |
|------------|---------|---------------|
| Поднятие резюме | Раз в 4 часа | Проверяем наличие активной кнопки |
| Лимит откликов/день | ~200 | Лимит 5 за запуск = ~10/день, безопасно |
| Повторный отклик | Нельзя на ту же вакансию | SQLite фиксирует все отклики |
| Антибот | WAF + JS-детект | Случайные задержки + реальный браузер |

---

## Что НЕ входит в MVP

- Telegram-уведомления
- Генерация персональных писем через Claude API
- Дашборд статистики
- Скоринг вакансий по AI
- Headless-режим (запуск без окна браузера) — добавить после тестирования

---

## Критерии готовности MVP

- [ ] `--login` сохраняет сессию, повторный запуск не требует пароля
- [ ] Резюме поднимается по расписанию, проверка кнопки работает корректно
- [ ] Вакансии фильтруются по config.py, дубли исключены через БД
- [ ] Откликов не более MAX_RESPONSES_PER_RUN за запуск
- [ ] Между откликами случайная задержка 10–30 секунд
- [ ] Все действия логируются, ошибки не роняют планировщик
- [ ] Режимы `--now-publish` и `--now-respond` работают
- [ ] README с инструкцией по установке и первому запуску

---

## Как передать в Claude Code

Скопируй в начало сессии:

```
Реализуй Python-проект по этому ТЗ.
Используй Playwright (async API) + APScheduler + SQLite.
Начни с browser.py и human_delay.py, затем database.py,
resume.py, vacancies.py, config.py, main.py.
После каждого модуля жди подтверждения перед следующим.
```
