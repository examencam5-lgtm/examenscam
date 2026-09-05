"""
database_search.py — ExamensCam
Fonctions de lecture sur 'search_index' (autocompletion) et
d'ecriture sur 'recherches_infructueuses' (signal strategique,
doc section 3.5 : les recherches sans resultat orientent les
prochaines priorites de scraping).

Import dans app.py :
    from database_search import rechercher, enregistrer_recherche_infructueuse, rechercher_avec_scoring

═══════════════════════════════════════════════════════
MIGRATION POSTGRES (NEON) — 04/09/2026
═══════════════════════════════════════════════════════
Même migration que les autres modules database_*.py :
  - sqlite3.connect(DB_PATH)        -> psycopg2.connect(DATABASE_URL)
  - conn.row_factory = sqlite3.Row  -> cursor_factory=RealDictCursor
  - placeholders '?'                -> placeholders '%s'
  - INTEGER PRIMARY KEY AUTOINCREMENT -> GENERATED ALWAYS AS IDENTITY
  - datetime('now')                 -> NOW()
  - conn.execute(...) direct        -> conn.cursor() puis cur.execute(...)

BONNE SURPRISE : la clause "ON CONFLICT(requete) DO UPDATE SET ..."
utilisée dans enregistrer_recherche_infructueuse() est déjà une
syntaxe standard SQL reprise à l'identique par SQLite (depuis 3.24) ET
Postgres -- aucune adaptation nécessaire sur cette partie précise.

⚠️ DÉPENDANCE EXTERNE NON RÉSOLUE : ce fichier interroge la table
`search_index` (fonctions rechercher() et rechercher_avec_scoring())
sans jamais la créer -- son create_table() se trouve probablement dans
generer_search_index.py (déjà importé ici pour normaliser()), non
fourni au moment de cette migration. Cette table doit exister côté
Postgres avant que la recherche fonctionne.

CE QUI NE CHANGE PAS : tous les alias, le scoring (calculer_score),
la normalisation de requête -- pure logique Python, aucun SQL,
inchangés à l'identique.
"""
import os
import re

import psycopg2
import psycopg2.extras

# Necessaire pour normaliser() les requetes.
from generer_search_index import normaliser

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "sur Render avec la chaine de connexion Postgres fournie par Neon "
        "-- sans elle, la recherche ne peut pas fonctionner."
    )

# ═══════════════════════════════════════════════════════
# ALIAS - Comprendre le langage des élèves
# ═══════════════════════════════════════════════════════

ALIAS_MATIERES = {
    'math': 'Mathématiques',
    'maths': 'Mathématiques',
    'm': 'Mathématiques',
    'mathematique': 'Mathématiques',
    'mathematiques': 'Mathématiques',
    'phys': 'Physique',
    'phy': 'Physique',
    'phisique': 'Physique',
    'physique': 'Physique',
    'chi': 'Chimie',
    'chim': 'Chimie',
    'chimie': 'Chimie',
    'shimie': 'Chimie',
    'svt': 'SVT',
    'sciences': 'SVT',
    'scien': 'SVT',
    'sience': 'SVT',
    'hist': 'Histoire-Géo',
    'geo': 'Histoire-Géo',
    'geographie': 'Histoire-Géo',
    'histoire': 'Histoire-Géo',
    'angl': 'Anglais',
    'ang': 'Anglais',
    'anglais': 'Anglais',
    'fr': 'Français',
    'francais': 'Français',
    'français': 'Français',
    'philo': 'Philosophie',
    'philosophie': 'Philosophie',
    'phylo': 'Philosophie',
    'info': 'Informatique',
    'informatique': 'Informatique',
    'dessin': 'Dessin Industriel',
    'latin': 'Latin',
    'eco': 'Economie',
    'economie': 'Economie',
    'ecm': 'ECM',
    'pct': 'PCT',
    'pc': 'Physique-Chimie',
    'allemand': 'Allemand',
    'espagnol': 'Espagnol',
    'litterature': 'Littérature',
    'littérature': 'Littérature',
    'langue': 'Langue Française',
}

ALIAS_NIVEAUX = {
    'bepc': 'BEPC',
    'probat': 'Probatoire',
    'prob': 'Probatoire',
    'bac': 'BAC',
    'term': 'BAC',
    'terminale': 'BAC',
    'premiere': 'Probatoire',
    '1ere': 'Probatoire',
    'troisieme': 'BEPC',
    '3eme': 'BEPC',
    '3e': 'BEPC',
}

ALIAS_SERIES = {
    'c': 'C',
    'd': 'D',
    'ti': 'TI',
    'a4': 'A4',
}

# ═══════════════════════════════════════════════════════
# PRIORITÉS DES MATIÈRES PAR SÉRIE (pour le scoring)
# ═══════════════════════════════════════════════════════

PRIORITES_MATIERES = {
    'A4': {
        'Littérature': 40,
        'Langue Française': 35,
        'Français': 35,
        'Anglais': 30,
        'Espagnol': 25,
        'Allemand': 25,
        'Chinois': 25,
        'Philosophie': 20,
        'Histoire-Géo': 15,
        'Economie': 15,
    },
    'C': {
        'Mathématiques': 40,
        'Physique': 35,
        'Chimie': 30,
        'SVT': 25,
        'Anglais': 20,
        'Littérature': 15,
        'Philosophie': 10,
    },
    'D': {
        'SVT': 40,
        'Mathématiques': 35,
        'Physique': 30,
        'Chimie': 25,
        'Anglais': 20,
        'Littérature': 15,
        'Philosophie': 10,
    },
    'TI': {
        'Informatique': 40,
        'Mathématiques': 35,
        'Physique': 30,
        'Chimie': 25,
        'Anglais': 20,
        'Littérature': 15,
        'Dessin Industriel': 10,
    },
    'BEPC': {
        'Mathématiques': 40,
        'PCT': 35,
        'SVTEEHB': 30,
        'SVT': 30,
        'Anglais': 25,
        'Étude de texte': 20,
        'Expression écrite': 20,
        'ECM': 15,
        'Histoire-Géo': 15,
        'Histoire': 15,
        'Géographie': 15,
    }
}

MATIERES_CANONIQUES = {
    'mathématiques': 'Mathématiques',
    'math': 'Mathématiques',
    'physique': 'Physique',
    'phys': 'Physique',
    'chimie': 'Chimie',
    'chim': 'Chimie',
    'svt': 'SVT',
    'anglais': 'Anglais',
    'angl': 'Anglais',
    'littérature': 'Littérature',
    'litterature': 'Littérature',
    'langue française': 'Langue Française',
    'français': 'Français',
    'francais': 'Français',
    'espagnol': 'Espagnol',
    'allemand': 'Allemand',
    'chinois': 'Chinois',
    'philosophie': 'Philosophie',
    'philo': 'Philosophie',
    'informatique': 'Informatique',
    'info': 'Informatique',
    'ecm': 'ECM',
    'pct': 'PCT',
    'svteehb': 'SVTEEHB',
    'etude de texte': 'Étude de texte',
    'expression ecrite': 'Expression écrite',
    'histoire-géo': 'Histoire-Géo',
    'histoire': 'Histoire-Géo',
    'géographie': 'Histoire-Géo',
    'economie': 'Economie',
    'dessin industriel': 'Dessin Industriel',
}


# ═══════════════════════════════════════════════════════
# FONCTIONS DE NORMALISATION -- INCHANGÉES (pure Python)
# ═══════════════════════════════════════════════════════

def normaliser_avec_alias(q: str) -> str:
    if not q or not q.strip():
        return q
    mots = q.lower().strip().split()
    mots_normalises = []
    for mot in mots:
        if mot in ALIAS_MATIERES:
            mots_normalises.append(ALIAS_MATIERES[mot])
        elif mot in ALIAS_NIVEAUX:
            mots_normalises.append(ALIAS_NIVEAUX[mot])
        elif mot in ALIAS_SERIES:
            mots_normalises.append(ALIAS_SERIES[mot])
        else:
            mots_normalises.append(mot)
    return ' '.join(mots_normalises)


def normaliser_requete_complete(q: str) -> dict:
    if not q or not q.strip():
        return {
            'query_normalisee': q,
            'niveau_detecte': None,
            'serie_detectee': None,
            'matiere_detectee': None,
            'annee_detectee': None
        }

    mots = q.lower().strip().split()
    mots_normalises = []

    result = {
        'query_normalisee': '',
        'niveau_detecte': None,
        'serie_detectee': None,
        'matiere_detectee': None,
        'annee_detectee': None
    }

    for mot in mots:
        if mot in ALIAS_MATIERES:
            valeur = ALIAS_MATIERES[mot]
            if not result['matiere_detectee']:
                result['matiere_detectee'] = valeur
            mots_normalises.append(valeur)
        elif mot in ALIAS_NIVEAUX:
            valeur = ALIAS_NIVEAUX[mot]
            if not result['niveau_detecte']:
                result['niveau_detecte'] = valeur
            mots_normalises.append(valeur)
        elif mot in ALIAS_SERIES:
            valeur = ALIAS_SERIES[mot]
            if not result['serie_detectee']:
                result['serie_detectee'] = valeur
            mots_normalises.append(valeur)
        elif re.match(r'^20\d{2}$', mot):
            result['annee_detectee'] = int(mot)
            mots_normalises.append(mot)
        else:
            mots_normalises.append(mot)

    result['query_normalisee'] = ' '.join(mots_normalises)
    return result


# ═══════════════════════════════════════════════════════
# FONCTIONS DE SUGGESTION -- INCHANGÉES (pure Python)
# ═══════════════════════════════════════════════════════

def suggerer_correction(q: str, niveau: str = None, serie: str = None) -> list:
    suggestions = []
    q_lower = q.lower().strip()

    if niveau and serie:
        if niveau.upper() == 'BEPC':
            priorites = PRIORITES_MATIERES.get('BEPC', {})
        else:
            priorites = PRIORITES_MATIERES.get(serie.upper(), {})

        matieres_prioritaires = sorted(priorites.items(), key=lambda x: x[1], reverse=True)[:5]
        for matiere, _ in matieres_prioritaires:
            if matiere.lower() not in q_lower and matiere not in suggestions:
                suggestions.append(matiere)

    for alias, valeur in ALIAS_MATIERES.items():
        if alias in q_lower or q_lower in alias:
            if valeur.lower() not in q_lower and valeur not in suggestions:
                suggestions.append(valeur)

    for alias, valeur in ALIAS_NIVEAUX.items():
        if alias in q_lower or q_lower in alias:
            if valeur.lower() not in q_lower and valeur not in suggestions:
                suggestions.append(valeur)

    for alias, valeur in ALIAS_SERIES.items():
        if alias in q_lower or q_lower in alias:
            if valeur.lower() not in q_lower and valeur not in suggestions:
                suggestions.append(valeur)

    corrections_communes = {
        'mathematique': 'Mathématiques',
        'mathe': 'Mathématiques',
        'physique': 'Physique',
        'chimie': 'Chimie',
        'francais': 'Français',
        'français': 'Français',
        'anglais': 'Anglais',
        'philosophie': 'Philosophie',
        'informatique': 'Informatique',
        'histoire': 'Histoire-Géo',
        'geographie': 'Histoire-Géo',
        'litterature': 'Littérature',
        'littérature': 'Littérature',
    }
    for faute, corrige in corrections_communes.items():
        if faute in q_lower or q_lower in faute:
            if corrige not in suggestions:
                suggestions.append(corrige)

    suggestions = list(dict.fromkeys(suggestions))
    return suggestions[:5]


# ═══════════════════════════════════════════════════════
# FONCTIONS DE BASE
# ═══════════════════════════════════════════════════════

def get_connection():
    """Retourne une connexion Postgres dont les curseurs renvoient des
    lignes de type dict (RealDictRow) -- même ergonomie que
    sqlite3.Row d'origine : row['colonne'] fonctionne à l'identique."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def creer_table_recherches_infructueuses():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recherches_infructueuses (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                requete TEXT NOT NULL,
                nombre_occurrences INTEGER DEFAULT 1,
                date_derniere TEXT DEFAULT (NOW()::text),
                UNIQUE(requete)
            );
        """)
        conn.commit()
    finally:
        conn.close()


def rechercher(q: str, limite: int = 8, niveau: str = None, serie: str = None, matiere: str = None) -> list[dict]:
    """
    Recherche multi-mots INDEPENDANTE DE L'ORDRE, filtrable par
    niveau/serie/matiere pour la personnalisation contextuelle :
    - accueil : aucun filtre -> tout l'index
    - page niveau (/bac) : niveau seul
    - page serie (/bac/C) : niveau + serie
    - page matiere (carrefour) : niveau + serie + matiere -> le plus precis

    ⚠️ Suppose que la table `search_index` existe déjà côté Postgres
    -- voir avertissement en tête de fichier."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        q_normalisee = normaliser(q)
        tokens = [t for t in q_normalisee.split() if t]
        if not tokens:
            return []

        filtre_sql = ""
        filtre_params = []
        if niveau:
            filtre_sql += " AND niveau = %s"
            filtre_params.append(niveau)
        if serie:
            filtre_sql += " AND serie = %s"
            filtre_params.append(serie)
        if matiere:
            filtre_sql += " AND matiere = %s"
            filtre_params.append(matiere)

        # Priorite 1 : phrase complete contigue (le signal le plus fiable,
        # ex: quelqu'un qui tape exactement "lycee classique d edea")
        cur.execute(f"""
            SELECT libelle, destination, type_source, niveau, matiere, serie
            FROM search_index
            WHERE libelle_recherche LIKE %s{filtre_sql}
            ORDER BY libelle
        """, (f"%{q_normalisee}%", *filtre_params))
        phrase_rows = cur.fetchall()

        # Priorite 2 : tous les mots presents, n'importe quel ordre --
        # c'est CA qui fait que "maths bac c" == "bac c maths".
        # Les tokens d'1 caractere (ex: le 'c' de serie C) sont
        # ignores ici -- LIKE '%c%' matcherait "chimie", "informatique"
        # etc., beaucoup trop large. Le scoring (calculer_score) gere
        # deja la precision de la serie via bonus_priorite, pas besoin
        # que le filtre SQL en depende.
        tokens_significatifs = [t for t in tokens if len(t) >= 2]

        if tokens_significatifs:
            conditions_mots = " AND ".join(["libelle_recherche LIKE %s" for _ in tokens_significatifs])
            params_mots = [f"%{t}%" for t in tokens_significatifs] + filtre_params
            cur.execute(f"""
                SELECT libelle, destination, type_source, niveau, matiere, serie
                FROM search_index
                WHERE {conditions_mots}{filtre_sql}
                ORDER BY libelle
            """, params_mots)
            tokens_rows = cur.fetchall()
        else:
            tokens_rows = []

        # Fusion en dedupliquant par destination -- phrase exacte
        # d'abord, puis le reste des matches multi-mots
        vus = set()
        resultats = []
        for r in list(phrase_rows) + list(tokens_rows):
            if r['destination'] in vus:
                continue
            vus.add(r['destination'])
            resultats.append(dict(r))
            if len(resultats) >= limite:
                break

        return resultats
    except Exception as e:
        print(f"rechercher error: {e}")
        return []
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════
# SCORING - Algorithme de pertinence -- INCHANGÉ (pure Python)
# ═══════════════════════════════════════════════════════

def calculer_score(item: dict, q: str, normalisation: dict) -> int:
    score = 0
    q_lower = q.lower()
    from datetime import datetime

    if item.get('matiere'):
        matiere_item = item['matiere'].lower()
        matiere_detectee = normalisation.get('matiere_detectee')
        niveau_detecte = normalisation.get('niveau_detecte')
        serie_detectee = normalisation.get('serie_detectee')

        matiere_canonique = None
        for alias, canonique in MATIERES_CANONIQUES.items():
            if alias in matiere_item or matiere_item in alias:
                matiere_canonique = canonique
                break
        if not matiere_canonique:
            matiere_canonique = matiere_item.title()

        bonus_priorite = 0
        if niveau_detecte == 'BEPC':
            priorites = PRIORITES_MATIERES.get('BEPC', {})
            bonus_priorite = priorites.get(matiere_canonique, 0)
        elif serie_detectee:
            priorites = PRIORITES_MATIERES.get(serie_detectee.upper(), {})
            bonus_priorite = priorites.get(matiere_canonique, 0)
            if bonus_priorite == 0 and item.get('serie'):
                priorites = PRIORITES_MATIERES.get(item['serie'].upper(), {})
                bonus_priorite = priorites.get(matiere_canonique, 0)

        if matiere_detectee:
            if matiere_detectee.lower() == matiere_item:
                score += 20 + bonus_priorite
            elif matiere_detectee.lower() in matiere_item:
                score += 15 + (bonus_priorite // 2)
            elif matiere_item in matiere_detectee.lower():
                score += 10 + (bonus_priorite // 3)
        else:
            for mot in q_lower.split():
                if len(mot) >= 3 and mot in matiere_item:
                    score += 10
                    break

    niveau_detecte = normalisation.get('niveau_detecte')
    if niveau_detecte and item.get('niveau'):
        niveau_item = (item['niveau'] or '').lower()
        niveau_req = niveau_detecte.lower()
        if niveau_req == niveau_item:
            score += 20
        elif niveau_req in niveau_item or niveau_item in niveau_req:
            score += 12

    serie_detectee = normalisation.get('serie_detectee')
    if serie_detectee and item.get('serie'):
        serie_item = item['serie'].upper()
        serie_req = serie_detectee.upper()
        if serie_req == serie_item:
            score += 15
        elif serie_req in serie_item or serie_item in serie_req:
            score += 8

    annee = None
    annee_match = re.search(r'(20\d{2})', item.get('libelle', ''))
    if annee_match:
        annee = int(annee_match.group(1))
    if not annee and normalisation.get('annee_detectee'):
        annee = normalisation.get('annee_detectee')

    if annee:
        annee_actuelle = datetime.now().year
        age = annee_actuelle - annee
        if age <= 1:
            score += 15
        elif age <= 2:
            score += 12
        elif age <= 3:
            score += 9
        elif age <= 5:
            score += 6
        elif age <= 10:
            score += 3

    vues = item.get('vues', 0)
    if vues > 0:
        if vues >= 1000:
            score += 10
        elif vues >= 500:
            score += 7
        elif vues >= 100:
            score += 4
        elif vues >= 10:
            score += 2
    type_source = item.get('type_source', '')
    if type_source == 'officiel':
        score += 10
    elif type_source == 'externe':
        libelle = item.get('libelle', '').lower()
        if 'corrigé' in libelle or 'corrige' in libelle:
            score += 3
        else:
            score += 1

    libelle = item.get('libelle', '').lower()
    if 'corrigé' in libelle or 'corrige' in libelle:
        score += 5

    return score


def rechercher_avec_scoring(q: str, limite: int = 8, niveau: str = None, serie: str = None, matiere: str = None) -> dict:
    """
    Version amelioree de rechercher() : alias + scoring + suggestions.
    Retourne {'resultats': [...], 'suggestions': [...],
              'requete_normalisee': '...', 'total_trouve': 0}
    """
    normalisation = normaliser_requete_complete(q)
    q_avec_alias = normalisation['query_normalisee']
    if not q_avec_alias:
        q_avec_alias = q

    resultats_bruts = rechercher(q_avec_alias, limite=limite * 3, niveau=niveau, serie=serie, matiere=matiere)

    resultats_enrichis = []
    for item in resultats_bruts:
        if item.get('type_source') == 'officiel':
            annee_match = re.search(r'#card-(\d{4})', item.get('destination', ''))
            item['annee'] = int(annee_match.group(1)) if annee_match else None
            try:
                conn = get_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT vues FROM annales
                        WHERE matiere = %s AND annee = %s
                        LIMIT 1
                    """, (item.get('matiere'), item.get('annee', 0)))
                    row = cur.fetchone()
                    item['vues'] = row['vues'] if row else 0
                finally:
                    conn.close()
            except Exception:
                item['vues'] = 0
        else:
            item['vues'] = 0

        if 'annee' not in item or not item['annee']:
            annee_match = re.search(r'(20\d{2})', item.get('libelle', ''))
            item['annee'] = int(annee_match.group(1)) if annee_match else None

        item['score'] = calculer_score(item, q, normalisation)
        resultats_enrichis.append(item)

    resultats_tries = sorted(resultats_enrichis, key=lambda x: x.get('score', 0), reverse=True)
    resultats_finaux = resultats_tries[:limite]

    suggestions = []
    if not resultats_finaux and len(q) >= 3:
        niveau_sugg = normalisation.get('niveau_detecte')
        serie_sugg = normalisation.get('serie_detectee')
        suggestions = suggerer_correction(q, niveau=niveau_sugg, serie=serie_sugg)

    return {
        'resultats': resultats_finaux,
        'suggestions': suggestions,
        'requete_normalisee': q_avec_alias,
        'total_trouve': len(resultats_tries)
    }


def enregistrer_recherche_infructueuse(q: str):
    """MIGRATION : la clause ON CONFLICT(requete) DO UPDATE SET ...
    est déjà une syntaxe Postgres valide telle quelle -- seul le
    placeholder '?' -> '%s' change ici."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO recherches_infructueuses (requete)
            VALUES (%s)
            ON CONFLICT(requete) DO UPDATE SET
                nombre_occurrences = recherches_infructueuses.nombre_occurrences + 1,
                date_derniere = NOW()::text
        """, (q,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"enregistrer_recherche_infructueuse error: {e}")
    finally:
        conn.close()


def get_recherches_infructueuses_frequentes(limite: int = 20) -> list[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT requete, nombre_occurrences, date_derniere
            FROM recherches_infructueuses
            ORDER BY nombre_occurrences DESC
            LIMIT %s
        """, (limite,))
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()