import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import init_db, get_connection

def main():
    print("Initializing SQLite database with WAL mode and Crumb Trail schemas...")
    init_db()
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    
    print(f"Database successfully initialized! Active tables: {tables}")

if __name__ == "__main__":
    main()

