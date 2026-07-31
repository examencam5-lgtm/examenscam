# nettoyer_doublons_test.py
"""
Supprime UNIQUEMENT les doublons causés par nos scripts de test
(source='TEST_TEMPORAIRE') dans la table 'annales'. Ne touche à
AUCUNE donnée réelle.

Usage : python nettoyer_doublons_test.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'
conn = sqlite3.connect(DB_PATH)

n = conn.execute("DELETE FROM annales WHERE source='TEST_TEMPORAIRE'").rowcount
conn.commit()
print(f"✅ {n} ligne(s) de test supprimée(s) de 'annales'.")
conn.close()
