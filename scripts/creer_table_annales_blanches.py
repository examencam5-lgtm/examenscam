# scripts/creer_table_annales_blanches.py
"""
CrÃ©e la table 'annales_blanches' : examens blancs / harmonisÃ©s rÃ©gionaux
/ olympiades / Ã©preuves zÃ©ro -- hÃ©bergÃ©s par Muhammad (comme les annales
officielles), mais PAS uniques par niveau/serie/matiere/annee, puisque
plusieurs rÃ©gions peuvent chacune avoir leur propre bac blanc la mÃªme
annÃ©e (ex: Bac Blanc Maths 2026 -- Ouest ET Centre existent tous les deux).

D'oÃ¹ une table sÃ©parÃ©e de 'annales' (qui elle doit rester unique --
un seul sujet OFFICIEL par combinaison), avec une contrainte adaptÃ©e.

Usage :
    python scripts/creer_table_annales_blanches.py
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
        CREATE TABLE IF NOT EXISTS annales_blanches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            niveau TEXT NOT NULL,
            serie TEXT,
            matiere TEXT NOT NULL,
            annee INTEGER NOT NULL,
            titre TEXT,
            region TEXT DEFAULT '', -- '' si national (jamais NULL, sinon UNIQUE ne dÃ©tecte pas les doublons)
            sequence INTEGER DEFAULT 0, -- 0 si sans sÃ©quence (jamais NULL, mÃªme raison)
            type_evaluation TEXT, -- 'Bac blanc', 'HarmonisÃ© rÃ©gional', 'Olympiade', 'Ã‰preuve zÃ©ro'
            lien_drive TEXT NOT NULL, -- hÃ©bergÃ© par toi, comme 'annales'
            corrige_dispo INTEGER DEFAULT 0,
            source TEXT,
            qualite TEXT DEFAULT 'bonne',
            vues INTEGER DEFAULT 0,
            date_ajout TEXT DEFAULT (datetime('now')),
            actif INTEGER DEFAULT 1,

            -- EmpÃªche le doublon rÃ©el (mÃªme sujet importÃ© deux fois),
            -- SANS bloquer la multiplicitÃ© rÃ©gion/sÃ©quence lÃ©gitime.
            UNIQUE(niveau, serie, matiere, annee, region, sequence, type_evaluation)
        );

        CREATE INDEX IF NOT EXISTS idx_blanches_niveau_serie ON annales_blanches(niveau, serie);
        CREATE INDEX IF NOT EXISTS idx_blanches_matiere ON annales_blanches(matiere);
        CREATE INDEX IF NOT EXISTS idx_blanches_region ON annales_blanches(region);
    """)

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM annales_blanches").fetchone()[0]
    print(f"âœ… Table 'annales_blanches' crÃ©Ã©e (ou dÃ©jÃ existante).")
    print(f" EntrÃ©es actuelles : {total}")
    conn.close()


if __name__ == "__main__":
    creer_table()
