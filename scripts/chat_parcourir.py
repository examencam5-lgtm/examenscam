"""
scripts/chat_parcourir.py — ExamensCam

Fonction de listing pour le bouton "Parcourir" du chat élève.

═══════════════════════════════════════════════════════
MIGRATION POSTGRES (NEON) + AJOUT DIMENSION ANNÉE — 05/09/2026
═══════════════════════════════════════════════════════

CE QUI CHANGE PAR RAPPORT À LA VERSION PRÉCÉDENTE :

1. sqlite3 -> psycopg2 (même raisonnement que les autres modules
   database_*.py, voir l'en-tête de database_eleves.py).

2. ⚠️ CORRECTIF CRITIQUE : l'ancienne version interrogeait une table
   `search_index` qui N'EXISTE PAS EN BASE -- generer_search_index.py
   (qui devait la créer) n'a jamais été fourni. Le bouton "Parcourir"
   plantait donc silencieusement à chaque appel. En attendant que
   cette table unifiée existe, lister_epreuves() interroge
   DIRECTEMENT les deux tables sources :
     - `annales`          (épreuves officielles, voir database.py)
     - `annales_externes` (épreuves d'établissements, voir
                            database_externes.py)
   C'est la décision explicite du 05/09/2026 : plutôt que de
   renvoyer une liste vide tant que search_index n'existe pas, on
   consulte tout ce qui est déjà disponible dans les deux tables
   réelles. Le jour où generer_search_index.py existe et que
   search_index est peuplée, on pourra basculer lister_epreuves() sur
   une requête unique dessus SANS changer sa signature ni le format
   des dicts retournés ({'libelle', 'destination', 'type_source',
   'annee'}) -- donc sans rien casser côté app.py ou du front qui
   consomme /chat/parcourir.

3. NOUVEAU : navigation à 4 niveaux au lieu de 3.
   AVANT : Niveau -> Série -> Matière -> résultats (max 8, triés par
           libellé décroissant, donc année "approximativement"
           récente d'abord pour les officiels seulement).
   APRÈS : Niveau -> Série -> Matière -> ANNÉE -> résultats.
   get_annees(niveau, matiere, serie) est la nouvelle fonction qui
   alimente cette 4e étape -- elle retourne les années RÉELLEMENT
   présentes (toutes sources confondues), pas une liste figée, pour
   qu'on ne propose jamais une année vide à l'élève.
   lister_epreuves() accepte maintenant un paramètre `annee` optionnel
   (rétrocompatible : appel sans `annee` = comportement large comme
   avant, mais sur les vraies tables cette fois).

STRUCTURE NIVEAU/SÉRIE : toujours codée en dur ici (inchangé) --
reflète l'organisation réelle du programme camerounais. Si cette
structure change, c'est ICI qu'il faut la mettre à jour, pas dans le
front.
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
        "-- sans elle, le bouton 'Parcourir' du chat ne peut rien lire."
    )

SERIES_PAR_NIVEAU = {
    "BEPC": [],
    "Probatoire": ["A", "C", "D"],
    "BAC": ["C", "D", "TI", "A4"],
}

NB_RESULTATS_PARCOURIR = 8


def get_connection():
    """Même ergonomie que les autres modules database_*.py : curseurs
    RealDictRow, accès par nom de colonne uniquement (row['colonne']),
    jamais par position (row[0])."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def get_niveaux() -> list[str]:
    return list(SERIES_PAR_NIVEAU.keys())


def get_series(niveau: str) -> list[str]:
    return SERIES_PAR_NIVEAU.get(niveau, [])


def get_annees(niveau: str, matiere: str, serie: Optional[str] = None) -> list[int]:
    """NOUVEAU (05/09/2026) -- 4e étape de la navigation "Parcourir".

    Retourne les années RÉELLEMENT disponibles pour ce
    niveau/série/matière, triées décroissant (plus récente d'abord).
    Ne propose jamais une année sans contenu derrière.

    Source PRINCIPALE : search_index (voir generer_search_index.py,
    colonne `annee` ajoutée le 05/09/2026 spécifiquement pour cette
    fonction) -- table unifiée, à jour dès que
    /admin/regenerer-index a été appelée après un import.

    FILET DE SÉCURITÉ : si search_index est vide ou n'existe pas
    encore (jamais régénérée, ou régénération en échec), on retombe
    sur une lecture directe de `annales` + `annales_externes` --
    c'est le principe explicite du 05/09/2026 : "dans le pire des
    cas, consulter tous les liens déjà disponibles" plutôt que de
    dépendre entièrement d'un index qui peut être périmé ou absent."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        query = "SELECT DISTINCT annee FROM search_index WHERE niveau=%s AND matiere=%s AND annee IS NOT NULL"
        params = [niveau, matiere]
        if serie:
            query += " AND (serie=%s OR serie IS NULL)"
            params.append(serie)
        elif niveau == "BEPC":
            query += " AND serie IS NULL"
        cur.execute(query, params)
        annees = {r['annee'] for r in cur.fetchall()}
        if annees:
            return sorted(annees, reverse=True)
    except Exception as e:
        print(f"get_annees (search_index) error, bascule sur le filet de sécurité: {e}")
    finally:
        conn.close()

    return _get_annees_direct(niveau, matiere, serie)


def _get_annees_direct(niveau: str, matiere: str, serie: Optional[str] = None) -> list[int]:
    """Filet de sécurité de get_annees() -- lecture directe des tables
    sources, voir doc de get_annees()."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        annees = set()

        query = "SELECT DISTINCT annee FROM annales WHERE niveau=%s AND matiere=%s AND actif=1"
        params = [niveau, matiere]
        if serie:
            query += " AND (serie=%s OR serie IS NULL)"
            params.append(serie)
        elif niveau == "BEPC":
            query += " AND serie IS NULL"
        cur.execute(query, params)
        annees.update(r['annee'] for r in cur.fetchall() if r['annee'] is not None)

        query_ext = "SELECT DISTINCT annee FROM annales_externes WHERE niveau=%s AND matiere=%s AND actif=1"
        params_ext = [niveau, matiere]
        if serie:
            query_ext += " AND (serie=%s OR serie IS NULL)"
            params_ext.append(serie)
        cur.execute(query_ext, params_ext)
        annees.update(r['annee'] for r in cur.fetchall() if r['annee'] is not None)

        return sorted(annees, reverse=True)
    except Exception as e:
        print(f"_get_annees_direct error: {e}")
        return []
    finally:
        conn.close()


def lister_epreuves(niveau: str, matiere: str, serie: Optional[str] = None,
                     annee: Optional[int] = None) -> list[dict]:
    """Retourne au plus NB_RESULTATS_PARCOURIR entrées
    {libelle, destination, type_source, annee}.

    Source PRINCIPALE : search_index -- destinations déjà correctes
    (ancre #card-<annee> pour l'officiel, /redirection/<id> pour
    l'externe qui journalise la vue avant de rediriger), et
    cohérente avec ce que renvoie la barre de recherche du site
    (/api/search, voir database_search.py) : "Parcourir" et
    "Rechercher" ne doivent jamais montrer des libellés différents
    pour le même contenu.

    FILET DE SÉCURITÉ : si search_index ne renvoie rien (vide,
    absente, ou pas encore régénérée depuis le dernier import), on
    retombe sur une lecture directe de `annales` + `annales_externes`
    -- jamais d'écran vide simplement parce que l'index est périmé."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        query = "SELECT libelle, destination, type_source, annee FROM search_index WHERE niveau=%s AND matiere=%s"
        params = [niveau, matiere]
        if serie:
            query += " AND (serie=%s OR serie IS NULL)"
            params.append(serie)
        elif niveau == "BEPC":
            query += " AND serie IS NULL"
        if annee:
            query += " AND annee=%s"
            params.append(annee)
        query += " ORDER BY annee DESC NULLS LAST LIMIT %s"
        params.append(NB_RESULTATS_PARCOURIR)
        cur.execute(query, params)
        resultats = [dict(r) for r in cur.fetchall()]
        if resultats:
            return resultats
    except Exception as e:
        print(f"lister_epreuves (search_index) error, bascule sur le filet de sécurité: {e}")
    finally:
        conn.close()

    return _lister_epreuves_direct(niveau, matiere, serie, annee)


def _lister_epreuves_direct(niveau: str, matiere: str, serie: Optional[str] = None,
                             annee: Optional[int] = None) -> list[dict]:
    """Filet de sécurité de lister_epreuves() -- lecture directe des
    tables sources, voir doc de lister_epreuves(). Les destinations
    ici sont moins abouties que via search_index (lien direct au lieu
    d'une ancre ou d'une route de journalisation), mais l'élève voit
    au moins un résultat plutôt qu'un écran vide."""
    conn = get_connection()
    resultats = []
    try:
        cur = conn.cursor()

        query = """
            SELECT niveau, serie, matiere, annee, lien_drive AS destination
            FROM annales WHERE niveau=%s AND matiere=%s AND actif=1
        """
        params = [niveau, matiere]
        if serie:
            query += " AND (serie=%s OR serie IS NULL)"
            params.append(serie)
        elif niveau == "BEPC":
            query += " AND serie IS NULL"
        if annee:
            query += " AND annee=%s"
            params.append(annee)
        query += " ORDER BY annee DESC"
        cur.execute(query, params)
        for r in cur.fetchall():
            suffixe_serie = f" {r['serie']}" if r['serie'] else ""
            resultats.append({
                'libelle': f"{r['niveau']}{suffixe_serie} {r['matiere']} {r['annee']}",
                'destination': r['destination'],
                'type_source': 'officiel',
                'annee': r['annee'],
            })

        query_ext = """
            SELECT niveau, serie, matiere, annee, id
            FROM annales_externes WHERE niveau=%s AND matiere=%s AND actif=1
        """
        params_ext = [niveau, matiere]
        if serie:
            query_ext += " AND (serie=%s OR serie IS NULL)"
            params_ext.append(serie)
        if annee:
            query_ext += " AND annee=%s"
            params_ext.append(annee)
        query_ext += " ORDER BY annee DESC"
        cur.execute(query_ext, params_ext)
        for r in cur.fetchall():
            suffixe_serie = f" {r['serie']}" if r['serie'] else ""
            resultats.append({
                'libelle': f"{r['niveau']}{suffixe_serie} {r['matiere']} {r['annee']} (établissement)",
                'destination': f"/redirection/{r['id']}",
                'type_source': 'externe',
                'annee': r['annee'],
            })

        resultats.sort(key=lambda r: r['annee'] or 0, reverse=True)
        return resultats[:NB_RESULTATS_PARCOURIR]
    except Exception as e:
        print(f"_lister_epreuves_direct error: {e}")
        return []
    finally:
        conn.close()