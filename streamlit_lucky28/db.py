import os, sqlite3
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(os.path.dirname(BASE_DIR), 'lucky28.db')

def db_exists() -> bool:
    return os.path.exists(DB_PATH)

@contextmanager
def get_conn():
    if not db_exists():
        raise FileNotFoundError(f'lucky28.db not found at {DB_PATH}')
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()
