import os
import json
import sqlite3
import pandas as pd
from pathlib import Path
import re

DATA_DIR = Path("data/sap-o2c-data")
DB_PATH = Path("graph.db")

def read_jsonl_folder(folder_path):
    data = []
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        return pd.DataFrame()
        
    for file_path in folder.glob("*.jsonl"):
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return pd.DataFrame(data)

def normalize_dataframe(df, table_name):
    if df.empty:
        return df

    # Convert column names to lowercase snake_case
    def to_snake_case(name):
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', str(name))
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower().replace('-', '_').replace(' ', '_')
        
    df.columns = [to_snake_case(col) for col in df.columns]

    # Strip whitespace from string columns and handle nested dicts/lists
    for col in df.columns:
        if df[col].dtype == 'object':
            df[col] = df[col].apply(lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x)
            df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)

    # Parse date/time fields
    for col in df.columns:
        if 'date' in col.lower() or 'time' in col.lower():
            try:
                parsed = pd.to_datetime(df[col], format='mixed', errors='coerce')
                df[col] = parsed.dt.strftime('%Y-%m-%d %H:%M:%S').combine_first(df[col])
            except Exception:
                pass

    # Fill missing values
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].fillna(0)
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            pass # Keep NaT for dates
        else:
            df[col] = df[col].fillna("")

    return df

def load_to_sqlite(df, table_name, conn):
    if df.empty:
        return
    df.to_sql(table_name, conn, if_exists="replace", index=False)
    print(f"Loaded {table_name}: {len(df)} rows, columns: {list(df.columns)}")

def main():
    if not DATA_DIR.exists():
        print(f"Data directory {DATA_DIR} does not exist.")
        return

    conn = sqlite3.connect(DB_PATH)
    summary = []

    for subfolder in DATA_DIR.iterdir():
        if subfolder.is_dir():
            table_name = subfolder.name.lower()
            df = read_jsonl_folder(subfolder)
            
            if df.empty:
                print(f"Skipping {table_name}: No data found.")
                continue
                
            df = normalize_dataframe(df, table_name)
            load_to_sqlite(df, table_name, conn)
            
            summary.append({"table_name": table_name, "row_count": len(df)})
            
    # Print summary
    print("\n--- Full Summary ---")
    if summary:
        summary_df = pd.DataFrame(summary)
        print(summary_df.to_string(index=False))
    else:
        print("No tables loaded.")

    conn.close()

if __name__ == "__main__":
    main()
