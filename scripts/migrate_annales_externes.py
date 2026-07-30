# scripts/migrate_annales_externes.py
"""
Migration : ajoute le support des liens externes (épreuves lycées/collèges)
à la table 'annales' existante, sans toucher aux annales officielles.

Usage (depuis la racine du projet) :
    python scripts/migrate_annales_externes.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def colonne_existe(conn, table, colonne) -> bool:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return colonne in [row[1] for row in cursor.fetchall()]


def migrer():
    conn = get_connection()

    nouvelles_colonnes = {
        "type_hebergement": "TEXT DEFAULT 'interne'",
        "etablissement": "TEXT",
        "lien_externe": "TEXT",
        "lien_page_source": "TEXT",
        "source_site": "TEXT",
        "region": "TEXT",
        "sequence": "INTEGER",
        "type_evaluation": "TEXT",
        "classe_detectee": "TEXT",
    }

    for nom, definition in nouvelles_colonnes.items():
        if colonne_existe(conn, "annales", nom):
            print(f" ⏭️ Colonne '{nom}' déjà présente, on saute.")
            continue
        conn.execute(f"ALTER TABLE annales ADD COLUMN {nom} {definition}")
        print(f" ✅ Colonne '{nom}' ajoutée.")

    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM annales").fetchone()[0]
    internes = conn.execute(
        "SELECT COUNT(*) FROM annales WHERE type_hebergement = 'interne'"
    ).fetchone()[0]

    print(f"\n✅ Migration terminée.")
    print(f" Total annales en base : {total}")
    print(f" Marquées 'interne' : {internes}")

    conn.close()

if __name__ == "__main__":
    migrer()

