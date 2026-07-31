# diagnostic_schema_annales.py
import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path('data') / 'annales.db')
print("=== Schéma réel de la table 'annales' ===\n")
for col in conn.execute("PRAGMA table_info(annales)").fetchall():
    print(f"  {col[1]:20s} {col[2]:10s} {'NOT NULL' if col[3] else ''}")
conn.close()
