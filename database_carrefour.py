"""
Fonction centrale pour la page "carrefour" (les branches entre le
choix de matière et les épreuves elles-mêmes).

Une seule fonction interroge les tables concernées et retourne les
compteurs nécessaires pour afficher des badges vivants sur chaque
branche (ex: "6 années", "23 épreuves indexées") au lieu de chiffres
statiques codés en dur dans le HTML.

═══════════════════════════════════════════════════════
SIMPLIFICATION (05/09/2026) -- BRANCHES CORRIGÉS RETIRÉES
═══════════════════════════════════════════════════════
La version précédente de ce fichier interrogeait TROIS tables qui
n'ont jamais existé nulle part, ni en SQLite ni en Postgres :
`packs_corriges`, `corriges_fichiers`, `annales_blanches`. Ce n'était
pas un oubli de migration -- c'est une fonctionnalité de corrigés
payants (V2, voir la doc de mémoire du projet) qui n'a jamais été
construite côté base de données. La page /carrefour plantait donc
systématiquement avec "relation does not exist" dès qu'un élève
cliquait dessus.

Décision (05/09/2026) : garder les branches qui reposent sur des
données réellement présentes (énoncés officiels, énoncés blancs,
énoncés établissements), et neutraliser proprement les deux branches
"pack corrigés" -- elles retournent None, pas une erreur, en attendant
que le système de corrigés payants soit réellement construit (V2).

CORRECTIF SUPPLÉMENTAIRE -- ÉNONCÉS BLANCS : il n'existe pas non plus
de table séparée `annales_blanches`. Les énoncés "blancs" sont déjà
dans la table `annales`, distingués par la colonne `type_sujet`
('officiel' ou 'blanc', voir database.py) -- exactement la même table
que les énoncés officiels, juste filtrée différemment. La branche 1
(officiels) filtrait auparavant sans préciser type_sujet, comptant
donc À TORT officiels ET blancs ensemble -- corrigé ici aussi.

═══════════════════════════════════════════════════════
MIGRATION POSTGRES (NEON) — 04/09/2026
═══════════════════════════════════════════════════════
  - sqlite3.connect(DB_PATH)        -> psycopg2.connect(DATABASE_URL)
  - conn.row_factory = sqlite3.Row  -> cursor_factory=RealDictCursor
  - placeholders '?'                -> placeholders '%s'
  - conn.execute(...) direct        -> conn.cursor() puis cur.execute(...)
  - COUNT(*) lu par position (row[0]) -> alias explicite (COUNT(*) AS n)
    et lecture par nom (row['n']), RealDictRow n'autorisant pas
    l'accès positionnel contrairement à sqlite3.Row.

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
    Retourne l'état des branches réellement disponibles pour un
    niveau/série/matière donné : énoncés officiels, énoncés blancs,
    énoncés établissements.

    Les branches "pack corrigés" (officiel_corriges, blancs_corriges)
    retournent toujours None pour l'instant -- fonctionnalité V2 non
    construite côté base de données (voir note en tête de fichier).
    Le template appelant doit gérer ce None en affichant "bientôt
    disponible" ou équivalent, pas en supposant que ces clés existent
    forcément avec des données.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()

        # ── Branche : Énoncés officiels ──
        # FIX (05/09/2026) : type_sujet='officiel' explicite -- avant,
        # cette requête comptait officiels ET blancs ensemble, faute de
        # filtre sur cette colonne.
        q1 = "SELECT COUNT(*) AS n FROM annales WHERE niveau=%s AND matiere=%s AND actif=1 AND type_sujet='officiel'"
        p1 = [niveau, matiere]
        if serie:
            q1 += " AND serie=%s"
            p1.append(serie)
        cur.execute(q1, p1)
        nb_officiel = cur.fetchone()['n']

        # ── Branche : Énoncés blancs ──
        # FIX (05/09/2026) : plus de table `annales_blanches` (n'a
        # jamais existé) -- les énoncés blancs vivent dans la même
        # table `annales`, distingués par type_sujet='blanc'.
        q3 = "SELECT COUNT(*) AS n FROM annales WHERE niveau=%s AND matiere=%s AND actif=1 AND type_sujet='blanc'"
        p3 = [niveau, matiere]
        if serie:
            q3 += " AND serie=%s"
            p3.append(serie)
        cur.execute(q3, p3)
        nb_blancs = cur.fetchone()['n']

        # ── Branche : Énoncés établissements ──
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
            # NEUTRALISÉ (05/09/2026) : pack corrigés officiels --
            # table packs_corriges jamais construite (V2, corrigés
            # payants). None signale explicitement "non disponible",
            # à distinguer d'un pack existant mais vide.
            "officiel_corriges": None,
            "blancs_enonces": {"nombre": nb_blancs},
            # NEUTRALISÉ (05/09/2026) : même raison que ci-dessus.
            "blancs_corriges": None,
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