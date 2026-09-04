"""
Fonctions de LECTURE pour la table 'annales_externes' (établissements).
import_liens_externes.py gere l'ecriture (scraping) ; ce fichier gere
la lecture pour affichage sur le site.

Filtre change : annee + sequence (au lieu de region + sequence) --
la region est moins utile pour l'eleve qui cherche un devoir precis
que l'annee, elle reste en donnee affichee mais plus en filtre
prioritaire.

═══════════════════════════════════════════════════════
MIGRATION POSTGRES (NEON) — 04/09/2026
═══════════════════════════════════════════════════════
Même migration que les autres modules database_*.py (voir l'en-tête
de database_eleves.py pour le raisonnement complet).

CE QUI CHANGE :
  - sqlite3.connect(DB_PATH)        -> psycopg2.connect(DATABASE_URL)
  - conn.row_factory = sqlite3.Row  -> cursor_factory=RealDictCursor
  - placeholders '?'                -> placeholders '%s'
  - conn.execute(...) direct        -> conn.cursor() puis cur.execute(...)

⚠️ CORRECTIF DE COMPATIBILITÉ IMPORTANT : get_annees_disponibles() et
get_sequences_disponibles() lisaient les colonnes par position (r[0])
-- ça fonctionne avec sqlite3.Row (accès positionnel ET nommé), mais
PAS avec RealDictRow de psycopg2 (dict pur, accès par nom de colonne
uniquement). Corrigé ici en accès par nom (r['annee'], r['sequence']).
Sans ce correctif, ces deux fonctions auraient levé une erreur à
l'exécution une fois basculées sur Postgres.

⚠️ DÉPENDANCE EXTERNE NON RÉSOLUE : ce fichier ne contient aucun
create_table() -- la table `annales_externes` doit exister au
préalable, créée par import_liens_externes.py (non fourni au moment
de cette migration). Ce script doit être adapté à Postgres séparément
avant que ces fonctions de lecture aient quoi que ce soit à lire.

CE QUI NE CHANGE PAS : tous les noms de fonctions, signatures et
valeurs de retour -- aucune modification nécessaire côté app.py.
"""

import os
from typing import Optional

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "sur Render avec la chaine de connexion Postgres fournie par Neon "
        "-- sans elle, les annales externes ne peuvent pas etre lues."
    )

CORRESPONDANCE_NIVEAU_SERIE = {
    "troisieme": ("BEPC", None),
    "premiere-a": ("Probatoire", "A"),
    "premiere-c": ("Probatoire", "C"),
    "premiere-d": ("Probatoire", "D"),
    "terminale-a": ("BAC", "A"),
    "terminale-c": ("BAC", "C"),
    "terminale-d": ("BAC", "D"),
}


def get_connection():
    """Retourne une connexion Postgres dont les curseurs renvoient des
    lignes de type dict (RealDictRow) -- accès par nom de colonne
    uniquement (row['colonne']), contrairement à sqlite3.Row qui
    permettait aussi l'accès positionnel (row[0])."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def get_matieres_externes(niveau_serie: str) -> list[dict]:
    if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
        return []
    niveau, serie = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]

    conn = get_connection()
    try:
        cur = conn.cursor()
        query = "SELECT matiere, COUNT(*) as nombre FROM annales_externes WHERE niveau=%s AND actif=1"
        params = [niveau]
        if serie:
            # Meme regle que database_matieres.py : serie IS NULL ne
            # "compte pour toutes les series" que pour BEPC. Ici serie
            # est toujours non-None dans CORRESPONDANCE_NIVEAU_SERIE sauf
            # pour 'troisieme' -> (BEPC, None), donc ce cas ne se presente
            # jamais pour BAC/Probatoire -- comparaison stricte suffit.
            query += " AND serie=%s"
            params.append(serie)
        query += " GROUP BY matiere ORDER BY matiere"

        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"get_matieres_externes error: {e}")
        return []
    finally:
        conn.close()


def get_annales_externes(niveau_serie: str, matiere: str, annee: Optional[int] = None,
                          sequence: Optional[int] = None) -> list[dict]:
    """Filtre par annee + sequence (remplace le filtre region + sequence)."""
    if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
        return []
    niveau, serie = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]
    conn = get_connection()
    try:
        cur = conn.cursor()
        query = "SELECT * FROM annales_externes WHERE niveau=%s AND matiere=%s AND actif=1"
        params = [niveau, matiere]
        if serie:
            query += " AND serie=%s"
            params.append(serie)
        if annee:
            query += " AND annee=%s"
            params.append(annee)
        if sequence:
            query += " AND sequence=%s"
            params.append(sequence)
        query += " ORDER BY annee DESC, date_ajout DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"get_annales_externes error: {e}")
        return []
    finally:
        conn.close()


def get_annale_externe_by_id(annale_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM annales_externes WHERE id=%s", (annale_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"get_annale_externe_by_id error: {e}")
        return None
    finally:
        conn.close()


def increment_vue_externe(annale_id: int):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE annales_externes SET vues = vues + 1 WHERE id=%s", (annale_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"increment_vue_externe error: {e}")
    finally:
        conn.close()


def get_annees_disponibles(niveau_serie: str, matiere: str) -> list[dict]:
    """
    Retourne les annees reellement presentes pour ce niveau/matiere,
    triees decroissant -- remplace get_regions_disponibles_externes
    comme filtre principal (doc : annee plus utile que region pour
    l'eleve qui cherche un devoir precis).

    MIGRATION : accès par nom de colonne (r['annee']) au lieu de
    positionnel (r[0]) -- voir avertissement en tête de fichier."""
    if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
        return []
    niveau, serie = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]
    conn = get_connection()
    try:
        cur = conn.cursor()
        query = """
            SELECT DISTINCT annee FROM annales_externes
            WHERE niveau=%s AND matiere=%s AND actif=1
        """
        params = [niveau, matiere]
        if serie:
            query += " AND serie=%s"
            params.append(serie)
        query += " ORDER BY annee DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        return [r['annee'] for r in rows]
    except Exception as e:
        print(f"get_annees_disponibles error: {e}")
        return []
    finally:
        conn.close()


def get_sequences_disponibles(niveau_serie: str, matiere: str) -> list[dict]:
    """Retourne TOUJOURS les séquences 1 à 6, avec flag 'disponible'.

    MIGRATION : accès par nom de colonne (r['sequence']) au lieu de
    positionnel (r[0]) -- voir avertissement en tête de fichier."""
    if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
        return [{"num": s, "disponible": False} for s in range(1, 7)]
    niveau, serie = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]
    conn = get_connection()
    try:
        cur = conn.cursor()
        query = """
            SELECT DISTINCT sequence FROM annales_externes
            WHERE niveau=%s AND matiere=%s AND actif=1 AND sequence IS NOT NULL
        """
        params = [niveau, matiere]
        if serie:
            query += " AND serie=%s"
            params.append(serie)
        cur.execute(query, params)
        rows = cur.fetchall()
        sequences_avec_donnees = {r['sequence'] for r in rows}
        return [{"num": s, "disponible": s in sequences_avec_donnees} for s in range(1, 7)]
    except Exception as e:
        print(f"get_sequences_disponibles error: {e}")
        return [{"num": s, "disponible": False} for s in range(1, 7)]
    finally:
        conn.close()