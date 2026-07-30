# verifier_svt_final.py
import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path('data') / 'annales.db')
print("=== Vérification finale ===\n")
for table in ["annales", "annales_blanches", "annales_externes", "packs_corriges"]:
    n_svt = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE matiere='SVT'").fetchone()[0]
    n_eehb = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE matiere='SVTEEHB'").fetchone()[0]
    print(f"  {table:20s} SVT={n_svt}  SVTEEHB={n_eehb}")
conn.close()