# verifier_svt_restant.py
import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path('data') / 'annales.db')

print("=== État actuel SVT vs SVTEEHB par table ===\n")
for table in ["annales", "annales_blanches", "annales_externes", "packs_corriges"]:
    for m in ["SVT", "SVTEEHB"]:
        n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE matiere=?", (m,)).fetchone()[0]
        print(f"  {table:20s} matiere='{m}' → {n}")
    print()

conn.close()