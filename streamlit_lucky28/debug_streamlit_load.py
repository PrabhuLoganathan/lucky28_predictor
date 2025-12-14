
import pandas as pd
import sqlite3
import os

# Mimic db.py logic (assuming common setups or referencing it)
# We need to know where db.py points, but let's try to find db.sqlite3 first.
# Usually it is in django_lucky28/db.sqlite3

DB_PATH = '/Users/nilav/Documents/GitHub/lucky28_predictor/lucky28.db'

def test_load():
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        query = "SELECT id, result, timestamp FROM gameapp_gameresult"
        df = pd.read_sql_query(query, conn, parse_dates=['timestamp'])
        
        print(f"Total rows in DF: {len(df)}")
        if not df.empty:
            print("Timestamp types:", df['timestamp'].dtype)
            print("First row:", df.iloc[0])
            print("Last row:", df.iloc[-1])
            
            # Simulate filter
            # 2025-12-14
            target_date = pd.to_datetime('2025-12-14').date()
            mask = (df['timestamp'].dt.date == target_date)
            filtered = df[mask]
            print(f"Rows matching {target_date}: {len(filtered)}")
            
            if len(filtered) == 0:
                print("Sample dates in DF:", df['timestamp'].dt.date.unique())
    finally:
        conn.close()

if __name__ == '__main__':
    test_load()
