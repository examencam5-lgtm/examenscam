"""
Fonction centrale pour la nouvelle page "carrefour" (les 5 branches
entre le choix de matière et les épreuves elles-mêmes).

Une seule fonction interroge les 4 tables concernées et retourne les
compteurs nécessaires pour afficher des badges vivants sur chaque
branche (ex: "6 années", "23 épreuves indexées", "4/7 corrigés prêts")
au lieu de chiffres statiques codés en dur dans le HTML.

═══════════════════════════════════════════════════════
MIGRATION POSTGRES (NEON) — 04/09/2026
═══════════════════════════════════════════════════════
Même migration que les autres modules database_*.py :
  - sqlite3.connect(DB_PATH)        -> psycopg2.connect(DATABASE_URL)
  - conn.row_factory = sqlite3.Row  -> cursor_factory=RealDictCursor
  - placeholders '?'                -> placeholders '%s'
  - conn.execute(...) direct        -> conn.cursor() puis cur.execute(...)

⚠️ CORRECTIF DE COMPATIBILITÉ : les COUNT(*) étaient lus par position
(.fetchone()[0]) -- fonctionne avec sqlite3.Row, PAS avec RealDictRow
de psycopg2 (dict pur, accès par nom de colonne uniquement). Corrigé
en ajoutant un alias explicite (COUNT(*) AS n) et en lisant row['n'].

⚠️ DÉPENDANCES EXTERNES NON RÉSOLUES : ce fichier interroge TROIS
tables dont aucun create_table() n'a été fourni à ce stade de la
migration : `packs_corriges`, `corriges_fichiers`, `annales_blanches`.
Ces tables doivent être créées côté Postgres (via leurs modules
respectifs, non encore migrés) AVANT que get_carrefour() fonctionne
-- sinon erreur "relation does not exist" sur les branches 2, 3 et 4.

Note technique sur la requête des packs (branches 2 et 4) : le
GROUP BY p.id avec p.titre et p.prix sélectionnés sans agrégation
fonctionne en Postgres SEULEMENT SI p.id est bien la clé primaire de
`packs_corriges` (dépendance fonctionnelle reconnue par Postgres
depuis la version 9.1) -- à vérifier une fois le schéma de cette
table en main.

CE QUI NE CHANGE PAS : get_slug_etablissements() est de la pure
logique Python (pas de SQL) -- inchangée à l'identique. Le fichier
reste volontairement en lecture seule, sans écriture ni commit.
"""

import os
from typing import Optional

import psycopg2
import psycopg2.extras

from database_externes import CORRESPONDANCE_NIVEAU_SERIE

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "sur Render avec la chaine de connexion Postgres fournie par Neon "
        "-- sans elle, la page carrefour ne peut afficher aucun compteur."
    )

# ── Pont entre les deux conventions de nomenclature ──
# officiel/blanc : niveau='BAC'/'Probatoire'/'BEPC', serie='C'/'D'/'A4'/'TI'
# établissements (scraping sujetexa) : niveau='BAC'/'Premiere', serie='A'/'C'/'D'
#
# Plutôt qu'une liste figée paire par paire (source d'oublis -- Probatoire D
# avait été oublié), le slug se construit automatiquement à partir d'une
# base par niveau + normalisation de la série.

BASE_SLUG_ETABLISSEMENTS = {
    "BAC": "terminale",
    "Premiere": "premiere",
    "Probatoire": "premiere",  # Probatoire partage le corpus sujetexa de Première
}

# Séries réellement couvertes par le scraping (voir CATEGORIES dans
# scrape_sujetexa.py). Toute série absente d'ici n'aura simplement pas
# de branche établissements -- comportement voulu, pas un bug.
SERIES_SCRAPEES = {"A", "C", "D"}


def get_slug_etablissements(niveau: str, serie: Optional[str]) -> Optional[str]:
    """
    Construit le slug établissements (ex: 'terminale-c', 'premiere-d')
    à partir du niveau et de la série. Retourne None si aucune
    correspondance sujetexa n'existe pour cette combinaison.

    INCHANGÉ par la migration -- logique Python pure, pas de SQL.
    """
    if niveau == "BEPC":
        return "troisieme"

    base = BASE_SLUG_ETABLISSEMENTS.get(niveau)
    if not base or not serie:
        return None

    # A4 (Probatoire/BAC) correspond à la catégorie 'a' côté sujetexa
    serie_normalisee = "A" if serie == "A4" else serie

    if serie_normalisee not in SERIES_SCRAPEES:
        return None  # ex: TI -- pas de catégorie sujetexa correspondante

    return f"{base}-{serie_normalisee.lower()}"


def get_connection():
    """Retourne une connexion Postgres dont les curseurs renvoient des
    lignes de type dict (RealDictRow) -- accès par nom de colonne
    uniquement, contrairement à sqlite3.Row qui permettait aussi
    l'accès positionnel (row[0])."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def get_carrefour(niveau: str, matiere: str, serie: Optional[str] = None) -> dict:
    """
    Retourne l'état des 5 branches pour un niveau/série/matière donné.
    Utilisé pour peupler la page carrefour avec des chiffres réels.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()

        # ── Branche 1 : Énoncés officiels ──
        q1 = "SELECT COUNT(*) AS n FROM annales WHERE niveau=%s AND matiere=%s AND actif=1"
        p1 = [niveau, matiere]
        if serie:
            q1 += " AND serie=%s"
            p1.append(serie)
        cur.execute(q1, p1)
        nb_officiel = cur.fetchone()['n']

        # ── Branche 2 : Pack corrigés officiels (progression) ──
        q2 = """
            SELECT p.id, p.titre, p.prix,
                   COUNT(c.id) AS total, SUM(CASE WHEN c.statut='pret' THEN 1 ELSE 0 END) AS prets
            FROM packs_corriges p
            LEFT JOIN corriges_fichiers c ON c.pack_id = p.id
            WHERE p.niveau=%s AND p.matiere=%s AND p.categorie='officiel' AND p.actif=1
        """
        p2 = [niveau, matiere]
        if serie:
            q2 += " AND p.serie=%s"
            p2.append(serie)
        q2 += " GROUP BY p.id ORDER BY p.annee_fin DESC LIMIT 1"
        cur.execute(q2, p2)
        pack_officiel = cur.fetchone()

        # ── Branche 3 : Énoncés blancs ──
        q3 = "SELECT COUNT(*) AS n FROM annales_blanches WHERE niveau=%s AND matiere=%s AND actif=1"
        p3 = [niveau, matiere]
        if serie:
            q3 += " AND serie=%s"
            p3.append(serie)
        cur.execute(q3, p3)
        nb_blancs = cur.fetchone()['n']

        # ── Branche 4 : Pack corrigés blancs (progression) ──
        q4 = q2.replace("categorie='officiel'", "categorie='blanc'")
        cur.execute(q4, p2)
        pack_blanc = cur.fetchone()

        # ── Branche 5 : Énoncés établissements ──
        # annales_externes utilise sa propre nomenclature (niveau='Premiere'
        # au lieu de 'Probatoire', par ex.) -- on traduit via le slug avant
        # d'interroger cette table.
        slug = get_slug_etablissements(niveau, serie)
        if slug and slug in CORRESPONDANCE_NIVEAU_SERIE:
            niveau_reel, serie_reel = CORRESPONDANCE_NIVEAU_SERIE[slug]
            q5 = "SELECT COUNT(*) AS n FROM annales_externes WHERE niveau=%s AND matiere=%s AND actif=1"
            p5 = [niveau_reel, matiere]
            if serie_reel:
                q5 += " AND serie=%s"
                p5.append(serie_reel)
            cur.execute(q5, p5)
            nb_etablissements = cur.fetchone()['n']
        else:
            nb_etablissements = 0

        return {
            "officiel_enonces": {"nombre": nb_officiel},
            "officiel_corriges": dict(pack_officiel) if pack_officiel else None,
            "blancs_enonces": {"nombre": nb_blancs},
            "blancs_corriges": dict(pack_blanc) if pack_blanc else None,
            "etablissements_enonces": {"nombre": nb_etablissements},
            "slug_etablissements": slug,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import json
    for niveau, serie in [("BAC", "C"), ("BAC", "D"), ("Probatoire", "C"),
                          ("Probatoire", "D"), ("Probatoire", "TI")]:
        print(f"\n{niveau} {serie} :")
        print(json.dumps(get_carrefour(niveau, "Mathematiques", serie=serie),
                         indent=2, ensure_ascii=False))