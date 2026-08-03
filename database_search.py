"""
database_search.py — ExamensCam
Fonctions de lecture sur 'search_index' (autocompletion) et
d'ecriture sur 'recherches_infructueuses' (signal strategique,
doc section 3.5 : les recherches sans resultat orientent les
prochaines priorites de scraping).

Import dans app.py :
    from database_search import rechercher, enregistrer_recherche_infructueuse, rechercher_avec_scoring
"""
import sqlite3
import re
import unicodedata  # ← AJOUTÉ
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'

# ═══════════════════════════════════════════════════════
# NORMALISATION (copie locale)
# ═══════════════════════════════════════════════════════

def normaliser(texte: str) -> str:
    """
    'LYCÉE Classique d'Édéa' -> 'lycee classique d edea'
    Retire les accents (NFKD + filtre des caracteres combinants),
    met en minuscules, remplace la ponctuation par des espaces.
    Necessaire pour que taper 'lycee' sans accent trouve 'LYCÉE'.
    """
    if not texte:
        return ""
    texte = texte.lower()
    texte = unicodedata.normalize('NFKD', texte)
    texte = ''.join(c for c in texte if not unicodedata.combining(c))
    # ponctuation -> espace, pour eviter de coller deux mots
    for char in "'’-_.,":
        texte = texte.replace(char, ' ')
    return ' '.join(texte.split())  # normalise les espaces multiples

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
    # BAC et Probatoire
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
    # BEPC (pas de série)
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

# Alias inversé pour trouver la matière canonique
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
# FONCTIONS DE NORMALISATION
# ═══════════════════════════════════════════════════════

def normaliser_avec_alias(q: str) -> str:
    """
    Transforme une requête utilisateur en utilisant les alias.
    Exemple: "math probat 2023" → "Mathématiques Probatoire 2023"
    """
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
    """
    Analyse la requête et extrait :
    - La requête normalisée
    - Niveau détecté
    - Série détectée
    - Matière détectée
    - Année détectée
    """
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
# FONCTIONS DE SUGGESTION
# ═══════════════════════════════════════════════════════

def suggerer_correction(q: str, niveau: str = None, serie: str = None) -> list:
    """
    Propose des corrections quand la recherche ne donne aucun résultat.
    Adapté au niveau et à la série pour suggérer les matières pertinentes.
    """
    suggestions = []
    q_lower = q.lower().strip()
    
    # 1. Si niveau et série sont fournis, suggérer les matières prioritaires
    if niveau and serie:
        if niveau.upper() == 'BEPC':
            priorites = PRIORITES_MATIERES.get('BEPC', {})
        else:
            priorites = PRIORITES_MATIERES.get(serie.upper(), {})
        
        matieres_prioritaires = sorted(priorites.items(), key=lambda x: x[1], reverse=True)[:5]
        for matiere, _ in matieres_prioritaires:
            if matiere.lower() not in q_lower and matiere not in suggestions:
                suggestions.append(matiere)
    
    # 2. Vérifier les alias de matière
    for alias, valeur in ALIAS_MATIERES.items():
        if alias in q_lower or q_lower in alias:
            if valeur.lower() not in q_lower and valeur not in suggestions:
                suggestions.append(valeur)
    
    # 3. Vérifier les alias de niveau
    for alias, valeur in ALIAS_NIVEAUX.items():
        if alias in q_lower or q_lower in alias:
            if valeur.lower() not in q_lower and valeur not in suggestions:
                suggestions.append(valeur)
    
    # 4. Vérifier les alias de série
    for alias, valeur in ALIAS_SERIES.items():
        if alias in q_lower or q_lower in alias:
            if valeur.lower() not in q_lower and valeur not in suggestions:
                suggestions.append(valeur)
    
    # 5. Corrections communes
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
    
    # 6. Supprimer les doublons et limiter à 5
    suggestions = list(dict.fromkeys(suggestions))
    return suggestions[:5]


# ═══════════════════════════════════════════════════════
# FONCTIONS DE BASE (non modifiées)
# ═══════════════════════════════════════════════════════

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def creer_table_recherches_infructueuses():
    """A appeler une fois (ou via create_table() dans database.py)."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recherches_infructueuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requete TEXT NOT NULL,
            nombre_occurrences INTEGER DEFAULT 1,
            date_derniere TEXT DEFAULT (datetime('now')),
            UNIQUE(requete)
        );
    """)
    conn.commit()
    conn.close()


def rechercher(q: str, limite: int = 8, niveau: str = None, matiere: str = None) -> list[dict]:
    """
    Recherche par pertinence pure (doc section 3.3). Filtrable par
    niveau et/ou matiere pour la recherche contextuelle par page :
    - accueil : niveau=None, matiere=None -> tout l'index
    - page niveau (ex: /bepc) : niveau='BEPC' -> scope au niveau
    - page carrefour matiere : niveau + matiere -> scope precis
    
    Cette fonction est NON MODIFIEE pour garantir la compatibilité.
    """
    conn = get_connection()
    try:
        q_normalisee = normaliser(q)

        filtre_sql = ""
        filtre_params = []
        if niveau:
            filtre_sql += " AND niveau = ?"
            filtre_params.append(niveau)
        if matiere:
            filtre_sql += " AND matiere = ?"
            filtre_params.append(matiere)

        debut = conn.execute(f"""
            SELECT libelle, destination, type_source
            FROM search_index
            WHERE libelle_recherche LIKE ?{filtre_sql}
            ORDER BY libelle
            LIMIT ?
        """, (f"{q_normalisee}%", *filtre_params, limite)).fetchall()

        resultats = [dict(r) for r in debut]

        if len(resultats) < limite:
            reste = limite - len(resultats)
            contient = conn.execute(f"""
                SELECT libelle, destination, type_source
                FROM search_index
                WHERE libelle_recherche LIKE ? AND libelle_recherche NOT LIKE ?{filtre_sql}
                ORDER BY libelle
                LIMIT ?
            """, (f"%{q_normalisee}%", f"{q_normalisee}%", *filtre_params, reste)).fetchall()
            resultats.extend([dict(r) for r in contient])

        return resultats
    except Exception as e:
        print(f"rechercher error: {e}")
        return []
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════
# SCORING - Algorithme de pertinence (PageRank-like)
# ═══════════════════════════════════════════════════════

def calculer_score(item: dict, q: str, normalisation: dict) -> int:
    """
    Calcule un score de pertinence pour chaque résultat.
    
    Scoring amélioré avec priorité des matières par série.
    
    Critères :
    - Match exact de la matière avec bonus série : 40 points max
    - Bonus niveau : 20 points
    - Bonus série : 15 points
    - Fraîcheur (année) : 15 points
    - Popularité (vues) : 10 points
    - Bonus source (type_source) : 5 points
    - Bonus qualité (titre contient "corrigé") : 5 points
    """
    score = 0
    q_lower = q.lower()
    from datetime import datetime
    
    # 1. MATCH EXACT DE LA MATIERE AVEC BONUS SÉRIE (40 points max)
    if 'matiere' in item:
        matiere_item = item['matiere'].lower()
        matiere_detectee = normalisation.get('matiere_detectee')
        niveau_detecte = normalisation.get('niveau_detecte')
        serie_detectee = normalisation.get('serie_detectee')
        
        # Trouver la matière canonique
        matiere_canonique = None
        for alias, canonique in MATIERES_CANONIQUES.items():
            if alias in matiere_item or matiere_item in alias:
                matiere_canonique = canonique
                break
        
        if not matiere_canonique:
            matiere_canonique = matiere_item.title()
        
        # Calculer le bonus de priorité selon la série
        bonus_priorite = 0
        if niveau_detecte == 'BEPC':
            priorites = PRIORITES_MATIERES.get('BEPC', {})
            bonus_priorite = priorites.get(matiere_canonique, 0)
        elif serie_detectee:
            # Essayer d'abord avec la série détectée
            priorites = PRIORITES_MATIERES.get(serie_detectee.upper(), {})
            bonus_priorite = priorites.get(matiere_canonique, 0)
            # Si pas trouvé, essayer avec la série de l'item
            if bonus_priorite == 0 and 'serie' in item and item['serie']:
                priorites = PRIORITES_MATIERES.get(item['serie'].upper(), {})
                bonus_priorite = priorites.get(matiere_canonique, 0)
        
        # Match exact
        if matiere_detectee:
            if matiere_detectee.lower() == matiere_item:
                score += 20 + bonus_priorite
            elif matiere_detectee.lower() in matiere_item:
                score += 15 + (bonus_priorite // 2)
            elif matiere_item in matiere_detectee.lower():
                score += 10 + (bonus_priorite // 3)
        else:
            # Match partiel avec les mots de la requête
            for mot in q_lower.split():
                if len(mot) >= 3 and mot in matiere_item:
                    score += 10
                    break
    
    # 2. BONUS NIVEAU (20 points)
    niveau_detecte = normalisation.get('niveau_detecte')
    if niveau_detecte and 'niveau' in item:
        niveau_item = (item['niveau'] or '').lower()
        niveau_req = niveau_detecte.lower()
        
        if niveau_req == niveau_item:
            score += 20
        elif niveau_req in niveau_item or niveau_item in niveau_req:
            score += 12
    
    # 3. BONUS SERIE (15 points)
    serie_detectee = normalisation.get('serie_detectee')
    if serie_detectee and 'serie' in item and item['serie']:
        serie_item = item['serie'].upper()
        serie_req = serie_detectee.upper()
        
        if serie_req == serie_item:
            score += 15
        elif serie_req in serie_item or serie_item in serie_req:
            score += 8
    
    # 4. FRAICHEUR (15 points)
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
    
    # 5. POPULARITE (10 points)
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
    
    # 6. BONUS SOURCE (5 points)
    type_source = item.get('type_source', '')
    if type_source == 'officiel':
        score += 5
    elif type_source == 'blanc':
        score += 3
    elif type_source == 'externe':
        # Bonus pour les externes si le titre contient "corrigé"
        libelle = item.get('libelle', '').lower()
        if 'corrigé' in libelle or 'corrige' in libelle:
            score += 3
        else:
            score += 2
    
    # 7. BONUS QUALITE (5 points) - titre contient "corrigé"
    libelle = item.get('libelle', '').lower()
    if 'corrigé' in libelle or 'corrige' in libelle:
        score += 5
    
    return score


# ═══════════════════════════════════════════════════════
# RECHERCHE AVEC SCORING
# ═══════════════════════════════════════════════════════

def rechercher_avec_scoring(q: str, limite: int = 8, niveau: str = None, matiere: str = None) -> dict:
    """
    Version améliorée de rechercher() qui utilise :
    - Les alias
    - Le scoring de pertinence
    - Les suggestions
    
    Retourne :
        {
            'resultats': [...],  # triés par score
            'suggestions': [...],
            'requete_normalisee': '...',
            'total_trouve': 0
        }
    """
    # 1. Normaliser la requête
    normalisation = normaliser_requete_complete(q)
    q_avec_alias = normalisation['query_normalisee']
    
    # 2. Si la requête normalisée est vide, utiliser l'originale
    if not q_avec_alias:
        q_avec_alias = q
    
    # 3. Récupérer les résultats (on prend plus pour le scoring)
    resultats_bruts = rechercher(q_avec_alias, limite=limite * 3, niveau=niveau, matiere=matiere)
    
    # 4. Enrichir avec les métadonnées et calculer le score
    resultats_enrichis = []
    
    for item in resultats_bruts:
        # Récupérer les vues pour les officiels
        if item.get('type_source') == 'officiel':
            # Extraire l'année depuis la destination (#card-YYYY)
            annee_match = re.search(r'#card-(\d{4})', item.get('destination', ''))
            if annee_match:
                item['annee'] = int(annee_match.group(1))
            else:
                item['annee'] = None
            
            # Chercher les vues dans la table annales
            try:
                conn = get_connection()
                row = conn.execute("""
                    SELECT vues FROM annales 
                    WHERE matiere = ? AND annee = ?
                    LIMIT 1
                """, (item.get('matiere'), item.get('annee', 0))).fetchone()
                if row:
                    item['vues'] = row['vues']
                else:
                    item['vues'] = 0
                conn.close()
            except:
                item['vues'] = 0
        else:
            item['vues'] = 0
        
        # Extraire l'année du libellé si pas déjà faite
        if 'annee' not in item or not item['annee']:
            annee_match = re.search(r'(20\d{2})', item.get('libelle', ''))
            if annee_match:
                item['annee'] = int(annee_match.group(1))
            else:
                item['annee'] = None
        
        # Calculer le score
        item['score'] = calculer_score(item, q, normalisation)
        resultats_enrichis.append(item)
    
    # 5. Trier par score décroissant
    resultats_tries = sorted(resultats_enrichis, key=lambda x: x.get('score', 0), reverse=True)
    
    # 6. Limiter le nombre de résultats
    resultats_finaux = resultats_tries[:limite]
    
    # 7. Suggestions si pas de résultats
    suggestions = []
    if not resultats_finaux and len(q) >= 3:
        # Déterminer niveau et série pour les suggestions
        niveau_sugg = normalisation.get('niveau_detecte')
        serie_sugg = normalisation.get('serie_detectee')
        suggestions = suggerer_correction(q, niveau=niveau_sugg, serie=serie_sugg)
    
    return {
        'resultats': resultats_finaux,
        'suggestions': suggestions,
        'requete_normalisee': q_avec_alias,
        'total_trouve': len(resultats_tries)
    }


# ═══════════════════════════════════════════════════════
# ENREGISTREMENT DES RECHERCHES INFructueuses
# ═══════════════════════════════════════════════════════

def enregistrer_recherche_infructueuse(q: str):
    """
    Incremente le compteur si la requete existe deja, sinon la cree.
    Signal gratuit de la demande reelle (doc section 3.5) -- a
    consulter periodiquement pour prioriser le scraping.
    """
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO recherches_infructueuses (requete)
            VALUES (?)
            ON CONFLICT(requete) DO UPDATE SET
                nombre_occurrences = nombre_occurrences + 1,
                date_derniere = datetime('now')
        """, (q,))
        conn.commit()
    except Exception as e:
        print(f"enregistrer_recherche_infructueuse error: {e}")
    finally:
        conn.close()


def get_recherches_infructueuses_frequentes(limite: int = 20) -> list[dict]:
    """Pour un futur dashboard admin -- les requetes les plus demandees sans resultat."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT requete, nombre_occurrences, date_derniere
            FROM recherches_infructueuses
            ORDER BY nombre_occurrences DESC
            LIMIT ?
        """, (limite,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()