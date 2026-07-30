# scripts/migrate_packs_categorie.py
"""
Ajoute la colonne 'categorie' à packs_corriges, pour distinguer
les packs de corrigés d'annales officielles de ceux d'examens blancs.
Un seul système de packs pour les deux catégories -- pas de table
dupliquée, juste un filtre.

Usage :
    python scripts/migrate_packs_categorie.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def migrer():
    conn = get_connection()

    colonnes = [r[1] for r in conn.execute("PRAGMA table_info(packs_corriges)").fetchall()]

    if "categorie" in colonnes:
        print("⏭️ Colonne 'categorie' déjà présente.")
    else:
        conn.execute("ALTER TABLE packs_corriges ADD COLUMN categorie TEXT DEFAULT 'officiel'")
        print("✅ Colonne 'categorie' ajoutée (valeur par défaut : 'officiel').")

    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM packs_corriges").fetchone()[0]
    officiels = conn.execute("SELECT COUNT(*) FROM packs_corriges WHERE categorie='officiel'").fetchone()[0]
    print(f" Total packs : {total} | Officiels : {officiels}")

    conn.close()


if __name__ == "__main__":
    migrer()
