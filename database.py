# database.py
import sqlite3
from pathlib import Path


def get_connection():
    Path('data').mkdir(exist_ok=True)
    conn = sqlite3.connect('data/annales.db')
    return conn

def create_table():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS annales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            niveau TEXT NOT NULL,
            serie TEXT,
            matiere TEXT NOT NULL,
            annee INTEGER NOT NULL,
            lien_drive TEXT,
            chemin_fichier TEXT,
            corrige_dispo INTEGER DEFAULT 0,
            vues INTEGER DEFAULT 0,
            actif INTEGER DEFAULT 1
        )
""")

    conn.commit()
    conn.close()
if __name__ == "__main__":
    create_table()
def check_table():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()

    print("Tables dans la base :", tables)

    conn.close()


if __name__ == "__main__":
    create_table()
    check_table() 