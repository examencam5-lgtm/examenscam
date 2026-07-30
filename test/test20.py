# verifier_annales_propre.py
import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path('data') / 'annales.db')
n = conn.execute("""
    SELECT COUNT(*) FROM annales
    WHERE type_hebergement='externe' OR source_site IS NOT NULL
""").fetchone()[0]
print(f"Lignes de scraping restantes dans 'annales' : {n}")

n_ext = conn.execute("SELECT COUNT(*) FROM annales_externes WHERE niveau='BAC' AND serie='C' AND source_site='sujetexa'").fetchone()[0]
print(f"Épreuves BAC C sujetexa dans annales_externes : {n_ext}")
conn.close()