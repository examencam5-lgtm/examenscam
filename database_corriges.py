# database_corriges.py
"""
Fonctions d'accès aux tables packs_corriges / corriges_fichiers.
Même style que database.py -- fichier séparé pour ne pas mélanger
avec la logique des annales officielles.

Import dans app.py :
    from database_corriges import get_packs_catalogue, get_pack_detail, creer_pack
"""

import sqlite3
from pathlib import Path
from typing import Optional

# Même chemin que database.py
DB_PATH = Path('data') / 'annales.db'


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def genere_titre(niveau: str, serie: Optional[str], matiere: str,
                  annee_debut: int, annee_fin: int) -> str:
    """Génère un titre lisible et cohérent automatiquement."""
    label = niveau
    if serie:
        label += f" {serie}"
    return f"Pack Corrigés {matiere} {label} {annee_debut}-{annee_fin}"


def creer_pack(niveau: str, matiere: str, annee_debut: int, annee_fin: int,
               serie: Optional[str] = None, prix: int = 500,
               description: Optional[str] = None) -> int:
    """
    Crée un nouveau pack. Retourne son ID.
    Le pack est créé actif mais SANS corrigé encore --
    utilise ajouter_corrige() ensuite pour le remplir.
    """
    titre = genere_titre(niveau, serie, matiere, annee_debut, annee_fin)
    conn = get_connection()

    try:
        cursor = conn.execute("""
            INSERT INTO packs_corriges
                (niveau, serie, matiere, annee_debut, annee_fin, titre, prix, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (niveau, serie, matiere, annee_debut, annee_fin, titre, prix, description))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        # Ce pack existe déjà (contrainte UNIQUE) -- on retourne son ID
        # existant plutôt que de planter, pour pouvoir relancer le script
        # sans casser sur les doublons.
        row = conn.execute("""
            SELECT id FROM packs_corriges
            WHERE niveau=? AND (serie=? OR (serie IS NULL AND ? IS NULL))
              AND matiere=? AND annee_debut=? AND annee_fin=?
        """, (niveau, serie, serie, matiere, annee_debut, annee_fin)).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def ajouter_corrige(pack_id: int, annee: int, lien_fichier: str = "",
                     statut: str = "brouillon") -> int:
    """Ajoute (ou met à jour) le corrigé d'une année précise dans un pack."""
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO corriges_fichiers (pack_id, annee, lien_fichier, statut)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(pack_id, annee) DO UPDATE SET
            lien_fichier = excluded.lien_fichier,
            statut = excluded.statut
    """, (pack_id, annee, lien_fichier, statut))
    conn.commit()
    nouvel_id = cursor.lastrowid
    conn.close()
    return nouvel_id


def get_packs_catalogue(niveau: Optional[str] = None,
                         serie: Optional[str] = None) -> list[dict]:
    """
    Retourne les packs actifs pour le catalogue, avec le nombre de
    corrigés réellement prêts vs le total attendu -- pour afficher
    honnêtement "4/7 corrigés disponibles" plutôt que de faire croire
    que tout est prêt.
    """
    conn = get_connection()

    query = """
        SELECT
            p.*,
            COUNT(c.id) AS total_annees_dans_pack,
            SUM(CASE WHEN c.statut = 'pret' THEN 1 ELSE 0 END) AS annees_pretes
        FROM packs_corriges p
        LEFT JOIN corriges_fichiers c ON c.pack_id = p.id
        WHERE p.actif = 1
    """
    params = []

    if niveau:
        query += " AND p.niveau = ?"
        params.append(niveau)
    if serie:
        query += " AND p.serie = ?"
        params.append(serie)

    query += " GROUP BY p.id ORDER BY p.niveau, p.serie, p.matiere"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pack_detail(pack_id: int) -> Optional[dict]:
    """Retourne le pack + la liste détaillée de ses corrigés."""
    conn = get_connection()

    pack = conn.execute("SELECT * FROM packs_corriges WHERE id = ?", (pack_id,)).fetchone()
    if not pack:
        conn.close()
        return None

    corriges = conn.execute("""
        SELECT * FROM corriges_fichiers WHERE pack_id = ? ORDER BY annee
    """, (pack_id,)).fetchall()

    conn.close()
    return {
        **dict(pack),
        "corriges": [dict(c) for c in corriges]
    }

def get_pack_par_matiere(niveau: str, serie: Optional[str], matiere: str) -> Optional[dict]:
    """
    Retrouve le pack correspondant à un niveau/serie/matiere -- utilisé
    par la route /corriges/<niveau>/<serie>/<matiere> pour passer de
    l'URL de navigation à l'ID réel du pack.
    Si plusieurs packs existent pour la même combinaison (tranches
    d'années différentes), retourne le plus récent (annee_fin la plus haute).
    """
    conn = get_connection()
    query = """
        SELECT * FROM packs_corriges
        WHERE niveau=? AND matiere=? AND actif=1
          AND (serie=? OR (serie IS NULL AND ? IS NULL))
        ORDER BY annee_fin DESC
        LIMIT 1
    """
    row = conn.execute(query, (niveau, matiere, serie, serie)).fetchone()
    conn.close()
    return dict(row) if row else None