import sqlite3
from query_engine import process

conn = sqlite3.connect('graph.db')

tests = [
    'Which products appear in the most billing documents?',
    'Show me all sales orders and their total values',
    'Which customers have the most orders?'
]

out = ""
for q in tests:
    res = process(q, conn)
    out += f"Q: {q}\n"
    out += f"SQL: {res['sql']}\n"
    out += f"ROWS: {len(res['data'])}\n"
    out += f"ANSWER: {res['answer']}\n"
    out += "---\n"

with open('final_out.txt', 'w', encoding='utf-8') as f:
    f.write(out)
