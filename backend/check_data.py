import sqlite3
conn = sqlite3.connect("graph.db")
cur = conn.cursor()

# Check the journal entry for reference doc 91150187
cur.execute("SELECT accounting_document, reference_document, customer FROM journal_entry_items_accounts_receivable WHERE reference_document = '91150187' LIMIT 10")
print("Journal entries for ref 91150187:", cur.fetchall())

# Check columns
cur.execute("PRAGMA table_info(journal_entry_items_accounts_receivable)")
print("Columns:", [r[1] for r in cur.fetchall()])

# Check sample rows
cur.execute("SELECT * FROM journal_entry_items_accounts_receivable LIMIT 3")
print("Sample rows:", cur.fetchall())
conn.close()
