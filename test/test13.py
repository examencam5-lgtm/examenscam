# nettoyer_vieux_doublons.py
"""
Supprime tous les anciens doublons BEPC identifiés (PCT 2015, PCT 2022,
Mathematiques 2020, Mathematiques 2023) -- Muhammad reconstruit ces
imports proprement depuis zéro.

Usage : python nettoyer_vieux_doublons.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'
conn = sqlite3.connect(DB_PATH)

ids_a_supprimer = [
    628, 629, 630,   # BEPC PCT 2015
    309, 310,        # BEPC Mathematiques 2020
    316, 317,        # BEPC Mathematiques 2023
    623, 624,         # BEPC PCT 2022
]

placeholders = ",".join("?" * len(ids_a_supprimer))
n = conn.execute(f"DELETE FROM annales WHERE id IN ({placeholders})", ids_a_supprimer).rowcount
conn.commit()
print(f"✅ {n} ligne(s) supprimée(s).")
conn.close()