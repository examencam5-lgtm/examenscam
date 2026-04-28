# init
# creer la base sqlite de examenscam

import sqlite3
from pathlib import Path

def init_db():
    Path('data').mkdir(exist_ok=True)

    conn = sqlite3.connect('data/annales.db')

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS annales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        niveau TEXT NOT NULL,
        serie TEXT,
        matiere TEXT NOT NULL,
        annee INTEGER NOT NULL,
        lien_drive TEXT NOT NULL,
        corrige_dispo INTEGER DEFAULT 0,
        source_fichier TEXT,
        vues INTEGER DEFAULT 0,
        actif INTEGER DEFAULT 1
    );
    """)

    conn.commit()
    conn.close()

    print("Base de donnees creee : data/annales.db")

init_db()