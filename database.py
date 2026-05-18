# database.py
# Base de données complète ExamensCam
# Toutes les fonctions utilisées par app.py sont ici

import sqlite3
from pathlib import Path
from typing import Optional

# ── CONFIGURATION ─────────────────────────────────────
DB_PATH = Path('data') / 'annales.db'


# ── CONNEXION ─────────────────────────────────────────
def get_connection():
    """Connexion à la base. Crée le dossier data/ si besoin."""
    Path('data').mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Accès par nom de colonne
    return conn


# ── INITIALISATION ────────────────────────────────────
def create_table():
    """
    Crée toutes les tables si elles n'existent pas.
    Peut être relancée sans danger — ne supprime rien.
    """
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
            actif INTEGER DEFAULT 1,
            UNIQUE(niveau, serie, matiere, annee) ON CONFLICT IGNORE
        );
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

        CREATE INDEX IF NOT EXISTS idx_niveau_serie
            ON annales(niveau, serie);

        CREATE INDEX IF NOT EXISTS idx_matiere
            ON annales(matiere);

        CREATE INDEX IF NOT EXISTS idx_annee
            ON annales(annee);
    """)
    conn.commit()
    conn.close()
    print("✅ Base de données prête :", DB_PATH)


# ── LECTURE ───────────────────────────────────────────

def get_matieres(niveau: str, serie: Optional[str] = None) -> list:
    """
    Retourne la liste des matières disponibles pour un niveau/série.

    Exemples :
        get_matieres('BEPC') → ['Mathematiques', 'PCT', ...]
        get_matieres('BAC', 'C') → ['Mathematiques', 'PCT', ...]
        get_matieres('Probatoire','D')→ ['Mathematiques', 'SVT', ...]
    """
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
        print(f"❌ get_matieres : {e}")
        return []
    finally:
        conn.close()


def get_annales(niveau: str,
                serie: Optional[str] = None,
                matiere: Optional[str] = None) -> list:
    """
    Récupère les annales selon les filtres.

    Exemples :
        get_annales('BEPC')
        get_annales('BAC', 'C')
        get_annales('BAC', 'C', 'Mathematiques')
        get_annales('Probatoire', 'D', 'SVT')
    """
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
        print(f"❌ get_annales : {e}")
        return []
    finally:
        conn.close()


def get_annale_by_id(annale_id: int) -> Optional[dict]:
    """Retourne une annale par son ID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM annales WHERE id = ? AND actif = 1",
            (annale_id,)
        ).fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"❌ get_annale_by_id : {e}")
        return None
    finally:
        conn.close()


def get_all_annales() -> list:
    """Retourne toutes les annales — pour le panel admin."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT * FROM annales
            WHERE actif = 1
            ORDER BY date_ajout DESC
        """).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"❌ get_all_annales : {e}")
        return []
    finally:
        conn.close()


def get_stats() -> dict:
    """
    Statistiques générales — utilisées sur la homepage et l'admin.

    Retourne :
        {
          'total': 42,
          'par_niveau': [{'niveau': 'BAC', 'n': 20}, ...],
          'top_vues': [{'matiere': 'Mathematiques', 'vues': 150}, ...]
        }
    """
    conn = get_connection()
    try:
        total = conn.execute(
            "SELECT COUNT(*) as n FROM annales WHERE actif = 1"
        ).fetchone()['n']

        par_niveau = conn.execute("""
            SELECT niveau, COUNT(*) as n
            FROM annales
            WHERE actif = 1
            GROUP BY niveau
            ORDER BY n DESC
        """).fetchall()

        top_vues = conn.execute("""
            SELECT niveau, serie, matiere, annee, vues
            FROM annales
            WHERE actif = 1
            ORDER BY vues DESC
            LIMIT 5
        """).fetchall()

        return {
            'total': total,
            'par_niveau': [dict(r) for r in par_niveau],
            'top_vues': [dict(r) for r in top_vues],
        }

    except Exception as e:
        print(f"❌ get_stats : {e}")
        return {'total': 0, 'par_niveau': [], 'top_vues': []}
    finally:
        conn.close()


# ── ÉCRITURE ──────────────────────────────────────────

def add_annale(niveau: str,
               serie: Optional[str],
               matiere: str,
               annee: int,
               lien_drive: str,
               corrige_dispo: bool = False,
               lien_corrige: Optional[str] = None,
               source: str = 'inconnu') -> int:
    """
    Ajoute une annale. Retourne l'ID créé.

    Exemple :
        add_annale('BAC', 'C', 'Mathematiques', 2023,
                   'https://drive.google.com/.../preview',
                   corrige_dispo=True,
                   source='sujetexa')
    """
    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO annales
                (niveau, serie, matiere, annee, lien_drive,
                 corrige_dispo, lien_corrige, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            niveau,
            serie or None,
            matiere,
            annee,
            lien_drive,
            int(corrige_dispo),
            lien_corrige or None,
            source
        ))
        conn.commit()
        new_id = cursor.lastrowid
        print(f"✅ Annale ajoutée : ID {new_id} — {niveau} {serie or ''} {matiere} {annee}")
        return new_id

    except sqlite3.IntegrityError as e:
        print(f"⚠️ DOUBLON ignoré : {niveau} {serie or ''} {matiere} {annee} — {e}")
        return 0
    except Exception as e:
        print(f"❌ ERREUR SQL add_annale : {type(e).__name__}: {e}")
        return -1
    finally:
        conn.close()


def delete_annale(annale_id: int) -> bool:
    """
    Suppression douce — met actif=0 sans effacer la ligne.
    Les données sont conservées pour l'historique.
    """
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE annales SET actif = 0 WHERE id = ?",
            (annale_id,)
        )
        conn.commit()
        print(f"✅ Annale {annale_id} désactivée")
        return True
    except Exception as e:
        print(f"❌ delete_annale : {e}")
        return False
    finally:
        conn.close()


def increment_vues(annale_id: int):
    """Incrémente le compteur de vues d'une annale."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE annales SET vues = vues + 1 WHERE id = ?",
            (annale_id,)
        )
        conn.commit()
    except Exception as e:
        print(f"❌ increment_vues : {e}")
    finally:
        conn.close()


# ── VÉRIFICATION ──────────────────────────────────────

def check_table():
    """Affiche les tables existantes — utile pour déboguer."""
    conn = get_connection()
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()
        print("Tables dans la base :", [t['name'] for t in tables])

        total = conn.execute(
            "SELECT COUNT(*) as n FROM annales"
        ).fetchone()['n']
        print(f"Annales en base : {total}")

    except Exception as e:
        print(f"❌ check_table : {e}")
    finally:
        conn.close()


# ── LANCEMENT DIRECT ──────────────────────────────────
if __name__ == "__main__":
    create_table()
    check_table()