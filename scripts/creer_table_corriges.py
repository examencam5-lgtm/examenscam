
# scripts/creer_tables_corriges.py
"""
Crée les tables nécessaires au catalogue des packs de corrigés.
Ne touche à rien d'existant (table 'annales' intacte).

Usage (depuis la racine du projet, là où se trouve database.py) :
    python scripts/creer_tables_corriges.py
"""

import sqlite3
from pathlib import Path

# Même chemin que dans database.py : 'data/annales.db'
# On duplique cette ligne ici plutôt que d'importer database.py,
# pour garder ce script totalement indépendant -- il ne dépend
# d'aucun autre fichier, donc pas de risque de casser database.py
# en le modifiant plus tard.
DB_PATH = Path('data') / 'annales.db'


def get_connection():
    """Identique à la fonction dans ton database.py."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def creer_tables():
    conn = get_connection()

    conn.executescript("""
        -- Un pack = un produit vendable : une matière+série précise,
        -- couvrant une tranche d'années, à un prix fixe.
        CREATE TABLE IF NOT EXISTS packs_corriges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            niveau TEXT NOT NULL,
            serie TEXT,
            matiere TEXT NOT NULL,
            annee_debut INTEGER NOT NULL,
            annee_fin INTEGER NOT NULL,
            titre TEXT NOT NULL,
            description TEXT,
            prix INTEGER NOT NULL DEFAULT 500,
            actif INTEGER DEFAULT 1,
            date_creation TEXT DEFAULT (datetime('now')),
            UNIQUE(niveau, serie, matiere, annee_debut, annee_fin)
        );

        -- Le contenu réel d'un pack : un corrigé par année.
        CREATE TABLE IF NOT EXISTS corriges_fichiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pack_id INTEGER NOT NULL REFERENCES packs_corriges(id),
            annee INTEGER NOT NULL,
            lien_fichier TEXT,
            statut TEXT DEFAULT 'brouillon',
            relu_par_muhammad INTEGER DEFAULT 0,
            date_ajout TEXT DEFAULT (datetime('now')),
            UNIQUE(pack_id, annee)
        );

        CREATE INDEX IF NOT EXISTS idx_packs_niveau_serie ON packs_corriges(niveau, serie);
        CREATE INDEX IF NOT EXISTS idx_corriges_pack ON corriges_fichiers(pack_id);
    """)

    conn.commit()

    total_packs = conn.execute("SELECT COUNT(*) FROM packs_corriges").fetchone()[0]
    print(f"✅ Tables créées avec succès.")
    print(f" Packs existants : {total_packs}")

    conn.close()


if __name__ == "__main__":
    creer_tables()

