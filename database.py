import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "responses.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.executescript("""
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

            CREATE TABLE IF NOT EXISTS resume_publishes (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                published_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                success      INTEGER,
                message      TEXT
            );

            CREATE TABLE IF NOT EXISTS manual_review (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                vacancy_id   TEXT NOT NULL UNIQUE,
                vacancy_title TEXT,
                company_name  TEXT,
                vacancy_url   TEXT,
                salary_text   TEXT,
                reason        TEXT,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS rate_limit_state (
                id           INTEGER PRIMARY KEY CHECK (id = 1),
                blocked_until DATETIME
            );
        """)


def is_already_responded(vacancy_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM responses WHERE vacancy_id = ?", (vacancy_id,)
        ).fetchone()
        return row is not None


def save_response(vacancy: dict) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO responses
               (vacancy_id, vacancy_title, company_name, vacancy_url, salary_text)
               VALUES (:vacancy_id, :vacancy_title, :company_name, :vacancy_url, :salary_text)""",
            vacancy,
        )


def save_publish(success: bool, message: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO resume_publishes (success, message) VALUES (?, ?)",
            (int(success), message),
        )


def save_manual_review(vacancy: dict, reason: str) -> None:
    """Сохранить вакансию, которую бот не смог обработать автоматически."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO manual_review
               (vacancy_id, vacancy_title, company_name, vacancy_url, salary_text, reason)
               VALUES (:vacancy_id, :vacancy_title, :company_name, :vacancy_url, :salary_text, :reason)
               ON CONFLICT(vacancy_id) DO UPDATE SET
                   reason = excluded.reason,
                   created_at = CURRENT_TIMESTAMP""",
            {**vacancy, "reason": reason},
        )


def is_in_manual_review(vacancy_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM manual_review WHERE vacancy_id = ?", (vacancy_id,)
        ).fetchone()
        return row is not None


def _paginate(rows: list[dict], search: str, fields: list[str], page: int, page_size: int) -> tuple[list[dict], int]:
    if search:
        q = search.lower()
        rows = [r for r in rows if any(q in (r.get(f) or "").lower() for f in fields)]
    total = len(rows)
    page = max(page, 1)
    start = (page - 1) * page_size
    return rows[start:start + page_size], total


def get_responses(search: str = "", page: int = 1, page_size: int = 15) -> tuple[list[dict], int]:
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT vacancy_title, company_name, vacancy_url, salary_text, responded_at "
            "FROM responses ORDER BY responded_at DESC"
        ).fetchall()]
    return _paginate(rows, search, ["vacancy_title", "company_name"], page, page_size)


def get_publishes(search: str = "", page: int = 1, page_size: int = 15) -> tuple[list[dict], int]:
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT success, message, published_at "
            "FROM resume_publishes ORDER BY published_at DESC"
        ).fetchall()]
    return _paginate(rows, search, ["message"], page, page_size)


def get_manual_review(search: str = "", page: int = 1, page_size: int = 15) -> tuple[list[dict], int]:
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT vacancy_title, company_name, vacancy_url, reason, created_at "
            "FROM manual_review ORDER BY created_at DESC"
        ).fetchall()]
    return _paginate(rows, search, ["vacancy_title", "company_name", "reason"], page, page_size)


def set_rate_limited(minutes: int) -> None:
    """Отметить, что hh.ru сообщил о превышении лимита откликов — отложить попытки на N минут."""
    blocked_until = datetime.utcnow() + timedelta(minutes=minutes)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO rate_limit_state (id, blocked_until) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET blocked_until = excluded.blocked_until",
            (blocked_until.isoformat(sep=" "),),
        )


def get_rate_limit_status() -> tuple[bool, "datetime | None"]:
    """Возвращает (заблокировано_ли_сейчас, до_какого_момента_UTC)."""
    with _connect() as conn:
        row = conn.execute("SELECT blocked_until FROM rate_limit_state WHERE id = 1").fetchone()
    if not row or not row["blocked_until"]:
        return False, None
    blocked_until = datetime.fromisoformat(row["blocked_until"])
    return datetime.utcnow() < blocked_until, blocked_until


def count_today_responses() -> int:
    """Кол-во откликов за сегодня по UTC (responded_at хранится в UTC через CURRENT_TIMESTAMP)."""
    today = datetime.utcnow().date().isoformat()
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM responses WHERE DATE(responded_at) = ?", (today,)
        ).fetchone()[0]


def get_stats() -> dict:
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
        today_count = count_today_responses()
        publishes = conn.execute(
            "SELECT COUNT(*) FROM resume_publishes WHERE success = 1"
        ).fetchone()[0]
        manual_count = conn.execute("SELECT COUNT(*) FROM manual_review").fetchone()[0]
    return {
        "total_responses": total,
        "today_responses": today_count,
        "total_publishes": publishes,
        "manual_review_count": manual_count,
    }
