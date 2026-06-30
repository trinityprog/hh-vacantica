import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# --- Авторизация ---
HH_LOGIN = os.getenv("HH_LOGIN", "")
HH_PASSWORD = os.getenv("HH_PASSWORD", "")

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
VACANCY_SCHEDULE_TIMES = ["09:05", "17:05"]
ONLY_NEW_VACANCIES = True
VACANCY_ITEMS_ON_PAGE = 100
VACANCY_SEARCH_PERIOD = 7  # дней

# --- Фильтры ---
SALARY_MIN = 0
KEYWORDS_REQUIRED: list[str] = []           # OR-поиск уже на стороне hh.ru
KEYWORDS_BLACKLIST = ["стажёр", "intern", "junior", "trainee"]
COMPANIES_BLACKLIST: list[str] = []
MAX_RESPONSES_PER_RUN = 5

# --- Безопасность ---
MIN_DELAY_BETWEEN_RESPONSES = 10
MAX_DELAY_BETWEEN_RESPONSES = 30

# --- Сопроводительное письмо ---
COVER_LETTER_TEMPLATE = os.getenv("COVER_LETTER", """Добрый день!

Откликаюсь на вашу вакансию. Имею опыт разработки на Python,
готов обсудить детали.

С уважением""")

# --- Пути ---
SESSION_PATH = os.path.join(os.path.dirname(__file__), "session", "state.json")
