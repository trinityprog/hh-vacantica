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
    "OR django OR nodejs OR typescript OR vue OR nextjs OR graphql OR yii OR fullstack"
)
VACANCY_SEARCH_FIELD = ["name", "company_name", "description"]  # поля поиска на hh.ru
VACANCY_AREA = 2                             # 2 = Алматы, 1 = Москва
VACANCY_INTERVAL_MINUTES = 2   # отклики идут непрерывно, прогон каждые N минут круглые сутки
ONLY_NEW_VACANCIES = True
VACANCY_ITEMS_ON_PAGE = 100
VACANCY_SEARCH_PERIOD = 7  # дней
VACANCY_MAX_PAGES = 3      # пагинация поиска на один прогон (~300 вакансий), не все 10 страниц каждый раз

# --- Фильтры ---
SALARY_MIN = 0
KEYWORDS_REQUIRED: list[str] = []           # OR-поиск уже на стороне hh.ru
KEYWORDS_BLACKLIST = ["стажёр", "intern", "junior", "trainee"]
COMPANIES_BLACKLIST: list[str] = []
# у hh.ru свой жёсткий лимит — 200 откликов в сутки на аккаунт.
# MAX_RESPONSES_PER_RUN держим маленьким, чтобы 200 растягивались на весь день
# (интервал VACANCY_INTERVAL_MINUTES × лимит распределяют попытки равномерно),
# а DAILY_RESPONSE_CAP — жёсткая остановка бота, чтобы не ловить ошибки/капчу hh.ru после лимита
MAX_RESPONSES_PER_RUN = 1
DAILY_RESPONSE_CAP = 200
RATE_LIMIT_BACKOFF_MINUTES = 60  # пауза после сообщения hh.ru "исчерпали лимит откликов"

# --- Безопасность ---
MIN_DELAY_BETWEEN_RESPONSES = 10
MAX_DELAY_BETWEEN_RESPONSES = 30

# --- Сопроводительное письмо ---
COVER_LETTER_TEMPLATE = os.getenv("COVER_LETTER", """Здравствуйте!

Меня заинтересовала ваша вакансия.

Я Fullstack-разработчик с более чем 8-летним коммерческим опытом разработки веб-приложений. Основная специализация — PHP (Laravel, Symfony), Python (FastAPI), React, Vue.js/Nuxt, PostgreSQL, MySQL, Redis, Docker и Linux.

За время работы занимался проектированием архитектуры, разработкой высоконагруженных backend-сервисов, REST API, интеграцией сторонних сервисов, оптимизацией производительности и развитием существующих продуктов. Есть опыт создания CRM-систем, внутренних платформ, микросервисов и AI-интеграций. Регулярно участвовал в code review, принимал архитектурные решения и взаимодействовал с командой на всех этапах разработки.

Быстро погружаюсь в новые проекты, умею самостоятельно находить оптимальные технические решения и доводить задачи до результата. Комфортно работаю как в команде, так и самостоятельно, всегда ориентируясь на качество кода и бизнес-ценность продукта.

Буду рад обсудить, каким образом мой опыт может быть полезен вашей команде.

Спасибо за внимание!
""")

# --- Пути ---
SESSION_PATH = os.path.join(os.path.dirname(__file__), "session", "state.json")
