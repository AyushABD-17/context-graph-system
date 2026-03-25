import sqlite3
import pandas as pd

conn = sqlite3.connect("graph.db")
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [r[0] for r in cursor.fetchall()]

for t in tables:
    df = pd.read_sql(f"SELECT * FROM {t} LIMIT 1", conn)
    print(f"{t}: {list(df.columns)}")
conn.close()
