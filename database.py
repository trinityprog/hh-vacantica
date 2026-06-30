import sqlite3
import os
from datetime import datetime, date

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


def get_stats() -> dict:
    today = date.today().isoformat()
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
        today_count = conn.execute(
            "SELECT COUNT(*) FROM responses WHERE DATE(responded_at) = ?", (today,)
        ).fetchone()[0]
        publishes = conn.execute(
            "SELECT COUNT(*) FROM resume_publishes WHERE success = 1"
        ).fetchone()[0]
    return {"total_responses": total, "today_responses": today_count, "total_publishes": publishes}
