# database.py — ExamensCam
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path('data') / 'annales.db'

def get_connection():
    Path('data').mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def create_table():
    Path('data').mkdir(exist_ok=True)
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS annales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            niveau TEXT NOT NULL,
            serie TEXT,
            matiere TEXT NOT NULL,
            annee INTEGER NOT NULL,
            lien_drive TEXT NOT NULL,
            corrige_dispo INTEGER DEFAULT 0,
            lien_corrige TEXT,
            source TEXT DEFAULT 'inconnu',
            qualite TEXT DEFAULT 'bonne',
            vues INTEGER DEFAULT 0,
            date_ajout TEXT DEFAULT (datetime('now')),
            actif INTEGER DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_niveau_serie ON annales(niveau, serie);
        CREATE INDEX IF NOT EXISTS idx_matiere ON annales(matiere);
        CREATE INDEX IF NOT EXISTS idx_annee ON annales(annee);

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            annale_id INTEGER REFERENCES annales(id),
            telephone TEXT NOT NULL,
            methode TEXT NOT NULL,
            montant INTEGER NOT NULL DEFAULT 1000,
            statut TEXT NOT NULL DEFAULT 'en_attente',
            reference TEXT,
            date_creation TEXT DEFAULT (datetime('now')),
            date_paiement TEXT
        );
    """)
    conn.commit()
    conn.close()

def get_matieres(niveau: str, serie: Optional[str] = None) -> list:
    conn = get_connection()
    try:
        if serie:
            rows = conn.execute("""
                SELECT DISTINCT matiere FROM annales
                WHERE niveau = ? AND serie = ? AND actif = 1
                ORDER BY matiere
            """, (niveau, serie)).fetchall()
        else:
            rows = conn.execute("""
                SELECT DISTINCT matiere FROM annales
                WHERE niveau = ? AND actif = 1
                ORDER BY matiere
            """, (niveau,)).fetchall()
        return [row['matiere'] for row in rows]
    except Exception as e:
        print(f"get_matieres error: {e}")
        return []
    finally:
        conn.close()

def get_annales(niveau: str, serie: Optional[str] = None,
                matiere: Optional[str] = None) -> list:
    conn = get_connection()
    try:
        query = "SELECT * FROM annales WHERE actif = 1"
        params = []
        if niveau:
            query += " AND niveau = ?"
            params.append(niveau)
        if serie:
            query += " AND serie = ?"
            params.append(serie)
        if matiere:
            query += " AND matiere = ?"
            params.append(matiere)
        query += " ORDER BY annee DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"get_annales error: {e}")
        return []
    finally:
        conn.close()

def get_annale_by_id(annale_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM annales WHERE id = ? AND actif = 1",
            (annale_id,)
        ).fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"get_annale_by_id error: {e}")
        return None
    finally:
        conn.close()

def get_all_annales() -> list:
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT * FROM annales
            WHERE actif = 1
            ORDER BY date_ajout DESC
        """).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"get_all_annales error: {e}")
        return []
    finally:
        conn.close()

def get_stats() -> dict:
    conn = get_connection()
    try:
        total = conn.execute(
            "SELECT COUNT(*) as n FROM annales WHERE actif = 1"
        ).fetchone()['n']
        par_niveau = conn.execute("""
            SELECT niveau, COUNT(*) as n FROM annales
            WHERE actif = 1 GROUP BY niveau ORDER BY n DESC
        """).fetchall()
        return {
            'total': total,
            'par_niveau': [dict(r) for r in par_niveau],
        }
    except Exception as e:
        print(f"get_stats error: {e}")
        return {'total': 0, 'par_niveau': []}
    finally:
        conn.close()

def add_annale(niveau: str, serie: Optional[str], matiere: str,
               annee: int, lien_drive: str, corrige_dispo: bool = False,
               lien_corrige: Optional[str] = None, source: str = 'inconnu') -> int:
    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO annales
                (niveau, serie, matiere, annee, lien_drive,
                 corrige_dispo, lien_corrige, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (niveau, serie or None, matiere, annee, lien_drive,
              int(corrige_dispo), lien_corrige or None, source))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        print(f"add_annale error: {e}")
        return -1
    finally:
        conn.close()

def delete_annale(annale_id: int) -> bool:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE annales SET actif = 0 WHERE id = ?", (annale_id,)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"delete_annale error: {e}")
        return False
    finally:
        conn.close()

def increment_vues(annale_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE annales SET vues = vues + 1 WHERE id = ?", (annale_id,)
        )
        conn.commit()
    except Exception as e:
        print(f"increment_vues error: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    create_table()
    print("Base de donnees prete :", DB_PATH)

