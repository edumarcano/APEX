import sqlite3
from datetime import datetime

DB_NAME = "apex_memory.db"


def initialize_db() -> None:
    """
    Initializes the database and creates the necessary tables.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, timestamp TEXT)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY, note TEXT, is_read INTEGER DEFAULT 0)''')
    
    conn.commit()
    conn.close()


def get_last_run() -> datetime | None:
    """
    Retrieves the timestamp of the last run from the database.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp FROM runs ORDER BY id DESC LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    return datetime.fromisoformat(result[0]) if result else None


def log_run() -> None:
    """
    Logs the current timestamp to the database.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO runs (timestamp) VALUES (?)", (datetime.now().isoformat(),))
    conn.commit()
    conn.close()


def save_reminder(note: str) -> None:
    """
    Saves a reminder to the database.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reminders (note) VALUES (?)", (note,))
    conn.commit()
    conn.close()


def fetch_unread_reminders() -> list[str]:
    """
    Fetches all unread reminders from the database and returns them as a list of tuples.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, note FROM reminders WHERE is_read = 0")
    records = cursor.fetchall()

    conn.close()
    return [record[1] for record in records]


def mark_all_reminders_read() -> None:
    """
    Marks all reminders as read in the database.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET is_read = 1 WHERE is_read = 0")
    conn.commit()
    conn.close()