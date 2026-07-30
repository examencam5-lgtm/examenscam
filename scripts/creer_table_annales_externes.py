# scripts/creer_table_annales_externes.py
"""
Crée une table SÉPARÉE pour les épreuves d'établissements (lycées/collèges).

Pourquoi une table séparée et pas une extension de 'annales' :
la table 'annales' a une contrainte UNIQUE(niveau, serie, matiere, annee)
-- une seule annale officielle par combinaison, ce qui est voulu pour
le pipeline officiel (INSERT OR IGNORE en dépend).

Mais côté établissements, PLUSIEURS collèges différents peuvent avoir
chacun leur "BAC C Maths 2026" -- la même combinaison niveau/serie/
matiere/annee doit pouvoir exister en dizaines d'exemplaires.
D'où la table séparée, avec sa propre contrainte adaptée : on empêche
seulement les VRAIS doublons (même lien PDF importé deux fois).

Usage :
    python scripts/creer_table_annales_externes.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def creer_table():
    conn = get_connection()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS annales_externes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            niveau TEXT NOT NULL,
            serie TEXT,
            matiere TEXT NOT NULL,
            annee INTEGER NOT NULL,
            titre TEXT,
            etablissement TEXT,
            region TEXT,
            sequence INTEGER,
            type_evaluation TEXT,
            classe_detectee TEXT,
            lien_externe TEXT NOT NULL,
            lien_page_source TEXT,
            source_site TEXT DEFAULT 'sujetexa',
            vues INTEGER DEFAULT 0,
            date_ajout TEXT DEFAULT (datetime('now')),
            actif INTEGER DEFAULT 1,

            -- On empêche seulement le vrai doublon : le même fichier
            -- PDF importé deux fois. Pas de contrainte sur
            -- niveau/serie/matiere/annee, contrairement à 'annales'.
            UNIQUE(lien_externe)
        );

        CREATE INDEX IF NOT EXISTS idx_ext_niveau_serie ON annales_externes(niveau, serie);
        CREATE INDEX IF NOT EXISTS idx_ext_matiere ON annales_externes(matiere);
        CREATE INDEX IF NOT EXISTS idx_ext_etablissement ON annales_externes(etablissement);
        CREATE INDEX IF NOT EXISTS idx_ext_region ON annales_externes(region);
    """)

    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM annales_externes").fetchone()[0]
    print(f"✅ Table 'annales_externes' créée (ou déjà existante).")
    print(f" Entrées actuelles : {total}")

    conn.close()


if __name__ == "__main__":
    creer_table()
