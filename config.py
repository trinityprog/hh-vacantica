import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# --- Авторизация ---
HH_LOGIN = os.getenv("HH_LOGIN", "")
HH_PASSWORD = os.getenv("HH_PASSWORD", "")
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

# --- Резюме ---
RESUME_TITLE = os.getenv("RESUME_TITLE", "Python разработчик")
RESUME_SCHEDULE_TIMES = ["09:00", "12:00", "17:00", "21:00"]
TIMEZONE = "Asia/Almaty"

# --- Поиск вакансий ---
VACANCY_SEARCH_TEXT = (
    "backend OR php OR laravel OR symfony OR python OR fastapi OR flask OR react "
    "OR django OR nodejs OR typescript OR vue OR nextjs OR graphql OR yii OR fullstack "
    "OR веб OR web"
)
VACANCY_SEARCH_FIELD = ["name", "company_name", "description"]  # поля поиска на hh.ru
VACANCY_AREA = 2                             # 2 = Алматы, 1 = Москва
VACANCY_INTERVAL_MINUTES = 15  # прогон каждые N минут (реже = меньше шанс капчи hh.ru)
VACANCY_INTERVAL_JITTER_SECONDS = 180  # случайный сдвиг запуска ±, чтобы не быть метрономом
RESPOND_ACTIVE_HOURS = (10, 22)  # бот откликается только в эти часы (по TIMEZONE); None = круглосуточно
ONLY_NEW_VACANCIES = True
VACANCY_ITEMS_ON_PAGE = 100
VACANCY_SEARCH_PERIOD = 7  # дней
VACANCY_MAX_PAGES = 3      # пагинация поиска на один прогон (~300 вакансий), не все 10 страниц каждый раз
NEGOTIATIONS_SYNC_INTERVAL_MINUTES = 30  # синхронизация статусов откликов (просмотрен/собеседование/отказ)

# --- Фильтры ---
SALARY_MIN = 0
KEYWORDS_REQUIRED: list[str] = []           # OR-поиск уже на стороне hh.ru
KEYWORDS_BLACKLIST = ["стажёр", "стажер", "intern", "junior", "trainee", "дизайнер", "туризм", "преподаватель"]
COMPANIES_BLACKLIST: list[str] = ["сбер", "sber", "т-банк", "тинькофф"]
# у hh.ru свой жёсткий лимит — 200 откликов в сутки на аккаунт.
# MAX_RESPONSES_PER_RUN держим маленьким, чтобы 200 растягивались на весь день
# (интервал VACANCY_INTERVAL_MINUTES × лимит распределяют попытки равномерно),
# а DAILY_RESPONSE_CAP — жёсткая остановка бота, чтобы не ловить ошибки/капчу hh.ru после лимита
MAX_RESPONSES_PER_RUN = 1
DAILY_RESPONSE_CAP = 200
RATE_LIMIT_BACKOFF_MINUTES = 60  # пауза после сообщения hh.ru "исчерпали лимит откликов"
CAPTCHA_BACKOFF_MINUTES = 10    # пауза после капчи hh.ru (бот её не решает)

# --- Безопасность ---
MIN_DELAY_BETWEEN_RESPONSES = 30
MAX_DELAY_BETWEEN_RESPONSES = 90

# --- Сопроводительное письмо ---
COVER_LETTER_TEMPLATE = os.getenv("COVER_LETTER", """Здравствуйте!

Меня зовут Денис, я Senior Fullstack Developer с 8+ годами опыта в разработке веб-приложений и backend-систем.

Основной стек: PHP (Laravel, Symfony), Python (FastAPI, Django), React, Vue.js, TypeScript, PostgreSQL, MySQL, Redis, Docker, REST API и микросервисная архитектура.

Работал как над разработкой проектов с нуля, так и над развитием и поддержкой production-систем. Есть опыт работы в команде и управления разработчиками, проектирования архитектуры, интеграций с внешними сервисами и оптимизации существующих решений.

В разработке активно использую AI-инструменты (Cursor, Claude Code, GitHub Copilot, ChatGPT) для ускорения написания и рефакторинга кода, анализа проектов, генерации тестов и документации.

Готов быстро погрузиться в ваш проект, разобраться в существующей архитектуре и взять на себя полноценную разработку или отдельные технические задачи.

Буду рад обсудить детали и показать релевантные проекты.
""")

# --- Профили поиска ---
# Бот по очереди (каждый прогон — следующий профиль) ищет вакансии под разные резюме.
# Профиль 1 — исходный (разработка), резюме выбирает сам hh.ru.
# Профиль 2 — удалёнка, не-IT роли с упором на нейросети: ищем свежие вакансии
# (меньше конкуренции) и исключаем должности разработчика/тестировщика прямо в названии.
# Текст резюме для профиля 2: resumes/resume_ai_remote.md

_REMOTE_AI_WORDS = (
    'нейросеть OR нейросети OR ИИ OR AI OR "искусственный интеллект" OR ChatGPT '
    'OR промпт OR prompt OR midjourney OR LLM'
)
_REMOTE_ROLES = (
    'копирайтер OR "контент-менеджер" OR "контент менеджер" OR SMM OR маркетолог '
    'OR "менеджер проектов" OR "project manager" OR ассистент OR "помощник руководителя" '
    'OR аналитик OR рекрутер OR редактор OR "специалист по автоматизации" OR "no-code" '
    'OR "ai-тренер" OR разметка OR модератор'
)
# Намеренно НЕ берём «оператор», «менеджер по продажам», «менеджер по работе с клиентами»,
# «поддержка», «администратор»: hh.ru ищет фразы нестрого, и выдачу заполняют колл-центры
# и розница — ИИ-резюме там ни при чём (при желании добавьте сюда сами).
# hh.ru: NOT NAME:(...) исключает слова только из названия вакансии. Обычный NOT/excluded_text
# режет и описания (где «разработчики» просто упомянуты) — терялись бы нужные вакансии.
_REMOTE_EXCLUDE_IN_TITLE = [
    "разработчик", "developer", "программист", "тестировщик", "тестирование", "tester", "qa", "sdet",
    "devops", "backend", "frontend", "fullstack", "full-stack", "software engineer",
    "инженер-программист", "python", "php", "java", "javascript", "react", "ios", "android",
    "unity", "c#", "c++", ".net", "golang", "1с", "data scientist", "engineer",
    "ai-инженер", "ml-инженер",
]

_REMOTE_RESUME_TITLE = os.getenv(
    "RESUME_TITLE_REMOTE", "Специалист по нейросетям и автоматизации (ИИ-ассистент)"
)

# Название активного резюме в окне отклика (как на hh.ru)
_RECOMMENDED_RESUME_TITLE = os.getenv("RESUME_TITLE_RECOMMENDED", "Software Engineer")

# Какие профили участвуют в прогонах (по имени). Остальные — только вручную: --profile <имя>
ACTIVE_PROFILES = ["non_dev"]

# non_dev: удалённые вакансии не для разработчиков/тестировщиков, где нет жёсткого контроля присутствия.
# Белого списка названий нет (чтобы не терять неожиданные названия) — исключаем только очевидное.
_NON_DEV_TITLE_EXCLUDE = _REMOTE_EXCLUDE_IN_TITLE + [
    "оператор", "колл-центр", "call-центр", "call center", "сменный", "менеджер по продажам",
    "продавец", "администратор", "курьер", "водитель", "консультант по продажам",
    "руководитель отдела продаж", "холодные",
    "продаж", "репетитор", "фотограф", "креатор", "монтаж", "арбитраж", "трафик", "hunter",
    "дистрибьютор", "кибербезопас", "инженер", "дизайнер", "designer", "преподаватель",
    "бухгалтер", "юрист", "логист", "кладовщик", "повар", "официант", "няня", "уборщик",
]
# Фразы в описании, по которым вакансию пропускаем (строгий контроль присутствия / смены / продажи)
_NON_DEV_TITLE_WHITELIST = [
    "аналитик", "analyst", "product", "продукт", "проект", "project", "scrum", "delivery",
    "ассистент", "assistant", "помощник", "секретарь", "автоматиз", "automation", "no-code", "nocode",
    "нейросет", "ии", "ai", "промпт", "prompt", "llm", "контент", "content", "copywriter", "копирайт",
    "редактор", "smm", "смм", "писатель", "technical writer", "документац", "модератор", "разметк",
    "руководитель it", "head of it", "head of product", "cto", "тимлид", "team lead", "lead",
    "консультант по внедрению", "внедрению", "интеграци", "crm", "bi", "data", "данных",
    "маркетолог", "marketing", "seo", "подбор", "рекрутер", "hr", "персонал", "куратор", "координатор",
]
_NON_DEV_DESCRIPTION_FLAGS = [
    "сменный график", "сменный режим", "график 2/2", "график 5/2 с", "посменно", "в офисе",
    "гибрид", "ежедневные созвоны", "ежедневный созвон", "ежедневные стендап", "стендап",
    "daily", "тайм-трекер", "тайм трекер", "time tracker", "мониторинг активности",
    "холодные звонки", "холодных звонков", "план продаж", "кпи", "kpi", "обязательное присутствие",
    "на связи в течение рабочего дня", "онлайн в рабочее время",
]

SEARCH_PROFILES: list[dict] = [
    {
        "name": "non_dev",
        "search_text": "",                      # широкий поиск, без белого списка названий
        "search_field": [],
        "extra_params": {
            "work_format": "REMOTE",
            "order_by": "publication_time",
            "search_period": "3",
        },
        "title_blacklist": _NON_DEV_TITLE_EXCLUDE,
        "title_whitelist": _NON_DEV_TITLE_WHITELIST,
        "title_word_start": True,
        "description_blacklist": _NON_DEV_DESCRIPTION_FLAGS,
        # ТОЛЬКО второе резюме (ИИ/автоматизация). Старое «Software Engineer» бот не трогает.
        "resume_title": _REMOTE_RESUME_TITLE,
        "cover_letter": os.getenv("COVER_LETTER_NON_DEV", """Здравствуйте!

Меня зовут Денис. У меня 8+ лет в IT, из них значительная часть — руководство небольшой командой, постановка задач, работа с заказчиками и выстраивание процессов.

Умею быстро разбираться в новой предметной области, переводить запросы бизнеса в понятные требования и документы, автоматизировать рутину и доводить работу до результата. Нейросети использую ежедневно: для подготовки текстов и документации, анализа информации и ускорения типовых задач.

Работаю удалённо самостоятельно и ответственно, на связи в рабочее время.

Буду рад обсудить задачи подробнее.
"""),
        "max_pages": 3,
    },
    {
        # Рекомендации hh.ru («Подходящие вакансии») для активного резюме:
        # без текста запроса и без фильтра по названию — берём всё, что предлагает hh.ru.
        # Остаётся только чёрный список компаний (COMPANIES_BLACKLIST).
        "name": "recommended",
        "search_text": "",
        "search_field": [],
        "extra_params": {"from": "resumelist"},   # + resume=<id>, определяется по названию резюме
        "recommended_for_resume": _RECOMMENDED_RESUME_TITLE,
        # id резюме из ссылки hh.ru/search/vacancy?resume=<id>; если пусто — ищется по названию
        "resume_id": os.getenv("RESUME_ID_RECOMMENDED", "1a493021ff116290a50039ed1f6964384d5754"),
        "title_blacklist": [],
        "title_word_start": False,
        "resume_title": _RECOMMENDED_RESUME_TITLE,
        "cover_letter": COVER_LETTER_TEMPLATE,
        "max_pages": 3,
    },
    {
        "name": "dev",
        "search_text": VACANCY_SEARCH_TEXT,
        "search_field": VACANCY_SEARCH_FIELD,
        "extra_params": {},
        "title_blacklist": KEYWORDS_BLACKLIST,
        "title_word_start": False,      # как раньше: подстрока в названии
        "resume_title": None,           # None = не выбирать, резюме подставляет hh.ru
        "cover_letter": COVER_LETTER_TEMPLATE,
        "max_pages": VACANCY_MAX_PAGES,
    },
    {
        "name": "remote_ai",
        "search_text": (
            f"NAME:({_REMOTE_AI_WORDS} OR {_REMOTE_ROLES}) "
            "NOT NAME:(" + " OR ".join(
                w if w.isalnum() else f'"{w}"' for w in _REMOTE_EXCLUDE_IN_TITLE
            ) + ")"
        ),
        # Всё ищем ТОЛЬКО в названии: поиск ИИ-слов по описанию тянет продавцов и консультантов,
        # где «ИИ» упомянут мельком (проверено на живой выдаче hh.ru)
        "search_field": ["name"],
        "extra_params": {
            "work_format": "REMOTE",
            "order_by": "publication_time",   # самые свежие — по ним меньше всего откликов
            "search_period": "3",
        },
        "title_blacklist": _REMOTE_EXCLUDE_IN_TITLE,
        "title_word_start": True,       # «qa» режет «QA Engineer», но не «Aqua»
        # Название второго резюме на hh.ru — должно совпадать с «Желаемой должностью»
        "resume_title": os.getenv(
            "RESUME_TITLE_REMOTE", "Специалист по нейросетям и автоматизации (ИИ-ассистент)"
        ),
        "cover_letter": os.getenv("COVER_LETTER_REMOTE", """Здравствуйте!

Меня зовут Денис. Нейросети — мой ежедневный рабочий инструмент: с их помощью я быстро готовлю тексты и документы, разбираю информацию, автоматизирую рутину и собираю процессы, на которые раньше уходили часы.

За плечами 8+ лет в IT, в том числе опыт руководства командой: умею ставить задачи, договариваться с людьми и доводить дело до результата. Работаю удалённо — самостоятельно, ответственно, на связи.

Готов быстро включиться в вашу задачу, взять на себя рутину и показать, как ИИ сокращает сроки и расходы.

Буду рад обсудить детали.
"""),
        "max_pages": 3,
    },
]

# --- Пути ---
SESSION_PATH = os.path.join(os.path.dirname(__file__), "session", "state.json")
