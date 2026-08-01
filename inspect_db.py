"""
inspect_db.py — ExamensCam
Inspecte le schema REEL de data/annales.db (par opposition au schema
tel que defini dans database.py, qui peut avoir divergé apres des
ALTER TABLE manuels non recommites).

Usage :
    python inspect_db.py
"""
import sqlite3
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'


def inspect():
    if not DB_PATH.exists():
        print(f"ERREUR : {DB_PATH} introuvable. "
              f"Lance ce script depuis la racine du projet (la ou se trouve le dossier data/).")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 1. Liste des tables
    tables = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """).fetchall()

    print("=" * 60)
    print(f"TABLES TROUVEES DANS {DB_PATH} : {len(tables)}")
    print("=" * 60)

    for t in tables:
        table_name = t['name']
        print(f"\n--- {table_name} ---")

        # Schema exact (CREATE TABLE tel que stocke reellement)
        schema = conn.execute("""
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = ?
        """, (table_name,)).fetchone()
        print(schema['sql'])

        # Colonnes en detail (PRAGMA table_info)
        cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        print("\nColonnes :")
        for c in cols:
            nullable = "NOT NULL" if c['notnull'] else "nullable"
            default = f"DEFAULT {c['dflt_value']}" if c['dflt_value'] is not None else ""
            pk = "PRIMARY KEY" if c['pk'] else ""
            print(f"  - {c['name']:<20} {c['type']:<10} {nullable:<10} {default:<20} {pk}")

        # Index
        idx = conn.execute(f"PRAGMA index_list({table_name})").fetchall()
        if idx:
            print("\nIndex :")
            for i in idx:
                print(f"  - {i['name']}")

        # Nombre de lignes
        count = conn.execute(f"SELECT COUNT(*) as n FROM {table_name}").fetchone()['n']
        print(f"\nNombre de lignes : {count}")

    conn.close()
    print("\n" + "=" * 60)
    print("FIN INSPECTION")
    print("=" * 60)


if __name__ == '__main__':
    inspect()