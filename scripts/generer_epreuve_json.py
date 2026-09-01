# scripts/generer_epreuve_json.py
"""
ÉTAPE 4a (architecture robuste, révision du 23/08/2026) du pipeline
RAG Maths Terminale C.

MISE A JOUR (24/08/2026) : séquences 5 et 6 ajoutées au choix CLI --
aucune autre modification de logique n'était nécessaire, l'architecture
est déjà entièrement pilotée par les données de rag.db (voir
calculer_frequence_themes, calculer_bareme_moyen,
selectionner_exemples_style) : le numéro de séquence n'est jamais
associé à un programme codé en dur dans ce fichier.

EXTENSION du 26/08/2026 -- Examens officiels (Baccalauréat) :
Ajout d'un second mode de génération, à côté du mode "Séquence"
existant, qui n'est pas touché. Différences structurelles observées
sur les 7 vrais sujets Bac C/E (sessions 2019-2025, voir
data/rag_maths_bac_c/pdfs) ayant motivé ces changements :

  1. Pas de numéro de séquence -- un Examen couvre l'année entière.
  2. Split Ressources/Compétences NON constant même sur les vrais
     Examens officiels (15/5 pour 2021/2022/2024, 13,25/6,75 pour
     2023/2025) -- calculer_repartition_bareme() doit donc pouvoir
     dériver ce split depuis rag.db (type_document='examen') au lieu
     d'utiliser la moyenne 'compétences' des séquences.
  3. Coefficient et durée dépendent de la série (C ou E), jamais du
     numéro de séquence -- table COEFFICIENT_EXAMEN ci-dessous,
     construite à partir des vrais sujets, jamais devinée par Gemini.
  4. Certaines questions peuvent être réservées à une série précise
     (bloc "Série C exclusivement" / "Série E exclusivement" vu sur
     les sujets 2020 et 2021) -- voir Question.serie_applicable dans
     schema_epreuve.py et detecter_serie_incorrecte() dans
     valider_epreuve.py.

Le mode Séquence garde exactement son comportement actuel : tous les
nouveaux paramètres ont une valeur par défaut qui reproduit l'ancien
appel (type_document="Sequence", serie=None).

Différences par rapport à la version précédente :

  1. Utilise response_schema (Pydantic, voir schema_epreuve.py) au
     lieu de décrire le JSON attendu en texte dans le prompt. Le SDK
     garantit un JSON syntaxiquement valide -- reparer_echappements_latex()
     a donc disparu, elle n'a plus de raison d'être.
  2. NE GÉNÈRE PLUS DE CORRIGÉ (décision explicite du 22/08/2026) --
     on se concentre sur des énoncés fiables, calibrés et bien mis en
     forme. Ça règle aussi mécaniquement le bug où le corrigé de la
     Partie B était systématiquement tronqué : il n'est simplement
     plus demandé.
  3. Après parsing, le contenu passe par valider_epreuve.py AVANT
     d'être écrit sur disque. Si la validation échoue (LaTeX interdit,
     barème incohérent, fuite de méta-commentaire, série incorrecte),
     on redéclenche une génération -- jusqu'à 3 tentatives -- plutôt
     que d'écrire un contenu qu'on sait défectueux.
  4. FIX du 23/08/2026 -- barème total systématiquement faux (ex: 15
     au lieu de 20) : avant ce fix, construire_prompt() ne donnait au
     modèle qu'une MOYENNE indicative par type de partie ("Barème
     observé : ressources ~13.5 pts en moyenne"). Gemini dérivait sa
     propre répartition à partir de ça sans jamais vérifier que la
     somme retombe sur 20 -- cohérent en interne (sous-questions =
     exercice = partie) mais faux globalement. Maintenant la
     répartition est CALCULÉE EN PYTHON (fonction calculer_repartition_bareme)
     et injectée dans le prompt comme contrainte chiffrée obligatoire,
     pas comme indication que le modèle peut réinterpréter.

RÉVISION DU 23/08/2026 (soir) -- robustesse API + quota, phase de test :
  5. La gestion de l'API Gemini (fallback multi-modèles 429/503,
     fallback multi-clés) est déplacée dans scripts/gemini_client.py
     -- ce fichier ne fait plus que l'IMPORTER. Avant ce déplacement,
     extraire_entete_personnalisable.py importait
     generer_avec_fallback() DEPUIS ce fichier-ci, qui lui-même
     importait extraire_entete_personnalisable.py plus haut -> import
     circulaire, plantage au démarrage de app.py. gemini_client.py ne
     dépend d'aucun autre module du package scripts/, donc les trois
     fichiers qui en ont besoin (celui-ci, extraire_entete_personnalisable.py,
     extraire_entete_image.py) peuvent tous l'importer sans risque de
     cycle, peu importe l'ordre.

Nécessite : pip install -U google-genai pydantic
Nécessite : au moins une des variables d'environnement listées dans
            gemini_client.CLES_API_ENV

Usage CLI (terminal) :
    python generer_epreuve_json.py --sequence 2
    python generer_epreuve_json.py --type examen --serie C
    (le script pose ensuite quelques questions sur l'établissement)

Usage programmatique (depuis Flask, voir app.py) :
    from scripts.generer_epreuve_json import generer_epreuve_json
    chemin_json = generer_epreuve_json(2, {"region": "Extrême-Nord", ...})
    chemin_json = generer_epreuve_json(0, {...}, type_document="Examen", serie="C")
"""

import os
import json
import argparse
import sqlite3
import random
import time
from pathlib import Path
from datetime import datetime

from google.genai import types

if __package__:
    # Chargé comme membre du package scripts/ (import normal depuis
    # app.py, generer_epreuve_json.py, etc.) -- import relatif garanti
    # correct dans ce cas, aucune raison de retomber sur un fallback.
    from .schema_epreuve import EpreuveGeneree
    from .valider_epreuve import valider_epreuve_generee
    from .extraire_entete_personnalisable import extraire_entete, ExtractionEnteteEchouee
    from .personnaliser_entete import personnaliser_entete_image, decouper_a_la_fraction
    from .gemini_client import construire_clients, generer_avec_fallback, MODELE_PAR_DEFAUT
else:
    # Lancé directement (python generer_epreuve_json.py) -- __package__
    # vaut "" ou None, le dossier scripts/ est alors sur sys.path,
    # l'import absolu fonctionne.
    from schema_epreuve import EpreuveGeneree
    from valider_epreuve import valider_epreuve_generee
    from extraire_entete_personnalisable import extraire_entete, ExtractionEnteteEchouee
    from personnaliser_entete import personnaliser_entete_image, decouper_a_la_fraction
    from gemini_client import construire_clients, generer_avec_fallback, MODELE_PAR_DEFAUT
DOSSIER_ENTETES_FINALES = Path("data/rag_maths_bac_c/entetes_personnalisees")

DB_PATH = Path("data/rag_maths_bac_c/rag.db")
SORTIE_DIR = Path("data/rag_maths_bac_c/epreuves_json")

NB_EXEMPLES_STYLE = 4
LIMITE_CARACTERES_EXEMPLE = 6000

# Budget de sortie généreux : même sans corrigé, la granularité
# demandée (5-9 sous-questions par exercice x 3-4 exercices +
# situation-problème) peut représenter un contenu conséquent.
MAX_OUTPUT_TOKENS = 10000

# Nombre total de tentatives (génération + validation) avant
# d'abandonner pour de bon. Une tentative peut échouer soit côté
# API/réseau, soit côté validation métier (barème, LaTeX interdit...).
NB_TENTATIVES_MAX = 3
PAUSES_ENTRE_TENTATIVES = [0, 10, 20]  # secondes, pas de pause avant la 1ere

# Barème total non négociable pour une épreuve Terminale C -- MINESEC,
# valable aussi bien pour une séquence que pour un Examen officiel.
# Points de présentation fixes (convention observée sur le corpus).
# Tout le reste de la répartition (ressources / compétences) est
# dérivé de ces deux constantes + de la moyenne historique observée
# pour la partie compétences (séquence) ou pour la partie compétences
# des Examens (voir calculer_repartition_bareme).
BAREME_TOTAL = 20.0
PRESENTATION_POINTS = 0.5
BAREME_COMPETENCES_DEFAUT = 6.5  # utilisé si aucune donnée historique n'existe pour cette séquence
BAREME_COMPETENCES_DEFAUT_EXAMEN = 5.0  # utilisé si rag.db n'a aucun Examen structuré encore

# Séquences supportées par le générateur -- Maths Terminale C uniquement.
# MISE A JOUR (24/08/2026) : 5 et 6 ajoutées. Aucune de ces valeurs n'est
# associée ici à un programme figé : c'est purement une liste de garde
# pour la validation CLI (voir choices= dans main() plus bas) -- le
# contenu réel vient entièrement de rag.db pour le numéro demandé.
SEQUENCES_SUPPORTEES = [1, 2, 3, 4, 5, 6]

# Séries supportées pour un Examen officiel -- sans objet pour une
# épreuve de séquence, qui ne distingue pas C/E.
SERIES_SUPPORTEES = ["C", "E"]

# Coefficient et durée par série pour un Examen officiel MINESEC --
# valeurs observées sur les vrais sujets Bac (data/rag_maths_bac_c/pdfs,
# sessions 2019-2025). Convention stable depuis la session 2022 :
# coefficient 7(C)/6(E), durée 4 heures. Sessions 2019-2020 avaient un
# coefficient différent (5(C)/4(E)) -- non retenu ici car on calibre
# sur la convention la plus récente, cohérent avec le choix déjà fait
# pour les épreuves de séquence (pas de valeur "moyenne" arbitraire
# sur une donnée qui doit être exacte, jamais interpolée).
COEFFICIENT_EXAMEN = {"C": 7, "E": 6}
DUREE_EXAMEN = "4 heures"


def calculer_frequence_themes(conn, sequence: int, type_document: str = "sequence") -> list[tuple[str, int]]:
    """`type_document` filtre sur la colonne du même nom dans rag.db
    (valeurs déjà en place : 'sequence', 'examen', 'td',
    'evaluation_diverse', 'olympiade', 'devoir_harmonise', 'autre' --
    voir Scrape_rag_maths_tc.py). Passé en paramètre plutôt que codé
    en dur pour permettre le même calcul sur les Examens officiels
    sans dupliquer la fonction.

    Pour un Examen (`type_document='examen'`), `sequence` est ignoré
    par le filtre WHERE -- un Examen officiel n'a pas de numéro de
    séquence, il couvre le programme complet de l'année.

    FIX (26/08/2026) -- repli sur les thèmes séquence si aucun Examen
    n'est encore tagué par thème dans rag.db : importer_examens_bac.py
    remplit epreuves/parties/exercices/questions mais ne fait PAS le
    tagging exercice_themes (étape réservée à extraire_structure_gemini.py
    pour les séquences, jamais lancée sur les Examens pour économiser
    des appels Gemini). Sans ce repli, la requête JOIN ne renvoie rien
    et generer_epreuve_json() échoue avec 'Aucune donnée structurée' --
    correct au sens fail-loudly, mais bloquant pour un usage réel tant
    que le tagging par thème n'a pas été fait sur le corpus Examens.
    Le repli utilise les thèmes dominants toutes séquences confondues
    (proxy raisonnable : le programme de Terminale C est commun) --
    JAMAIS un thème inventé ou une liste codée en dur."""
    if type_document == "examen":
        cur = conn.execute("""
            SELECT t.nom_theme, COUNT(*) as freq
            FROM epreuves e
            JOIN parties p ON p.epreuve_id = e.id
            JOIN exercices ex ON ex.partie_id = p.id
            JOIN exercice_themes et ON et.exercice_id = ex.id
            JOIN themes t ON t.id = et.theme_id
            WHERE e.type_document = 'examen'
              AND e.matiere_suspecte = 0
            GROUP BY t.nom_theme
            ORDER BY freq DESC
        """)
        resultats = cur.fetchall()
        if resultats:
            return resultats

        # Repli : aucun Examen tagué par thème pour l'instant --
        # utilise les thèmes dominants sur TOUTES les séquences
        # confondues plutôt que d'échouer. Signalé explicitement par
        # un print (pas une exception : c'est un repli volontaire,
        # pas une erreur silencieuse -- le prof reçoit quand même une
        # épreuve calibrée sur des thèmes réels du programme).
        print("⚠️  Aucun thème tagué pour les Examens officiels dans rag.db -- "
              "repli sur les thèmes dominants toutes séquences confondues.")
        cur = conn.execute("""
            SELECT t.nom_theme, COUNT(*) as freq
            FROM epreuves e
            JOIN parties p ON p.epreuve_id = e.id
            JOIN exercices ex ON ex.partie_id = p.id
            JOIN exercice_themes et ON et.exercice_id = ex.id
            JOIN themes t ON t.id = et.theme_id
            WHERE e.type_document = 'sequence'
              AND e.matiere_suspecte = 0
            GROUP BY t.nom_theme
            ORDER BY freq DESC
        """)
        return cur.fetchall()

    cur = conn.execute("""
        SELECT t.nom_theme, COUNT(*) as freq
        FROM epreuves e
        JOIN parties p ON p.epreuve_id = e.id
        JOIN exercices ex ON ex.partie_id = p.id
        JOIN exercice_themes et ON et.exercice_id = ex.id
        JOIN themes t ON t.id = et.theme_id
        WHERE e.sequence = ?
          AND e.type_document = 'sequence'
          AND e.matiere_suspecte = 0
        GROUP BY t.nom_theme
        ORDER BY freq DESC
    """, (sequence,))
    return cur.fetchall()


def calculer_bareme_moyen(conn, sequence: int, type_document: str = "sequence") -> dict:
    """Voir calculer_frequence_themes() pour la logique de `type_document`
    -- même principe, même filtre conditionnel."""
    if type_document == "examen":
        cur = conn.execute("""
            SELECT p.type_partie, AVG(p.bareme_points), COUNT(*)
            FROM epreuves e
            JOIN parties p ON p.epreuve_id = e.id
            WHERE e.type_document = 'examen'
              AND e.matiere_suspecte = 0
              AND p.bareme_points IS NOT NULL
            GROUP BY p.type_partie
        """)
    else:
        cur = conn.execute("""
            SELECT p.type_partie, AVG(p.bareme_points), COUNT(*)
            FROM epreuves e
            JOIN parties p ON p.epreuve_id = e.id
            WHERE e.sequence = ?
              AND e.type_document = 'sequence'
              AND e.matiere_suspecte = 0
              AND p.bareme_points IS NOT NULL
            GROUP BY p.type_partie
        """, (sequence,))
    return {tp: (round(m, 1), c) for tp, m, c in cur.fetchall()}


def calculer_repartition_bareme(baremes: dict, type_document: str = "sequence") -> dict:
    """Calcule la répartition EXACTE et OBLIGATOIRE du barème total
    (20 points), à partir de la moyenne historique observée pour la
    partie compétences. La partie ressources récupère tout le reste --
    c'est ce calcul, fait en Python et jamais laissé au modèle, qui
    garantit que la somme finale fait exactement 20.

    Avant ce fix, seule une moyenne indicative était donnée au modèle
    dans le prompt ("Barème observé : ~13.5 pts en moyenne") --
    Gemini dérivait sa propre répartition à partir de ça sans jamais
    vérifier la somme globale, d'où des totaux faux (ex: 15/20)
    détectés par valider_baremes() dans valider_epreuve.py.

    EXTENSION du 26/08/2026 : le défaut utilisé quand rag.db n'a pas
    (encore) assez de données historiques diffère selon
    `type_document` -- BAREME_COMPETENCES_DEFAUT_EXAMEN (5.0, cohérent
    avec le split 15/5 observé sur la majorité des vrais sujets Bac
    2021/2022/2024) plutôt que BAREME_COMPETENCES_DEFAUT (6.5, calibré
    sur les séquences). Dès que rag.db contient plusieurs Examens
    structurés, la moyenne réelle prend le dessus sur ce défaut, exactement
    comme pour les séquences.

    Retourne un dict avec des valeurs déjà arrondies à 0.5 point près
    (convention MINESEC -- pas de quart de point sur le barème des
    parties, seulement sur les sous-questions individuelles)."""
    defaut = BAREME_COMPETENCES_DEFAUT_EXAMEN if type_document == "examen" else BAREME_COMPETENCES_DEFAUT
    bareme_competences_brut = baremes.get("competences", (defaut, 0))[0]

    # Arrondi au demi-point le plus proche pour rester dans la
    # convention MINESEC observée sur le corpus (une PARTIE entière
    # n'a jamais un barème du type 6.3 ou 6.7).
    bareme_competences = round(bareme_competences_brut * 2) / 2
    bareme_ressources = BAREME_TOTAL - bareme_competences - PRESENTATION_POINTS

    return {
        "ressources": bareme_ressources,
        "competences": bareme_competences,
        "presentation": PRESENTATION_POINTS,
    }


def selectionner_exemples_style(conn, sequence: int, n: int, type_document: str = "sequence") -> list[str]:
    """Voir calculer_frequence_themes() pour la logique de `type_document`."""
    if type_document == "examen":
        cur = conn.execute("""
            SELECT texte_extrait FROM epreuves
            WHERE type_document = 'examen'
              AND matiere_suspecte = 0 AND statut_extraction = 'ok'
              AND LENGTH(texte_extrait) > 500
        """)
    else:
        cur = conn.execute("""
            SELECT texte_extrait FROM epreuves
            WHERE sequence = ? AND type_document = 'sequence'
              AND matiere_suspecte = 0 AND statut_extraction = 'ok'
              AND LENGTH(texte_extrait) > 500
        """, (sequence,))
    tous = [row[0] for row in cur.fetchall()]
    echantillon = random.sample(tous, min(n, len(tous)))
    return [t[:LIMITE_CARACTERES_EXEMPLE] for t in echantillon]


def demander_metadonnees_utilisateur(defauts: dict | None = None) -> dict:
    """UNIQUEMENT pour l'usage CLI -- Flask construit le dict de
    métadonnées directement depuis le formulaire web (pré-rempli côté
    JS avec le résultat de extraire_metadonnees_entete()).

    `defauts` : dict optionnel issu de extraire_metadonnees_entete()
    (lecture d'une vraie épreuve uploadée). Chaque champ devient la
    valeur par défaut proposée -- le prof tape Entrée pour l'accepter,
    ou une nouvelle valeur pour l'écraser (ex: mettre à jour l'année
    scolaire plutôt que garder celle de l'épreuve source). Aucun champ
    n'est jamais imposé : c'est toujours le prof qui a le dernier mot."""
    defauts = defauts or {}

    print("═" * 60)
    print("INFORMATIONS POUR L'EN-TÊTE DE L'ÉPREUVE")
    if defauts:
        confiance = defauts.get("confiance", "?")
        print(f"(pré-rempli depuis une épreuve uploadée -- confiance de lecture : {confiance})")
        print("Appuie sur Entrée pour garder la valeur proposée, ou tape une nouvelle valeur.")
    print("═" * 60)

    def _demander(label: str, cle: str, defaut_final: str) -> str:
        propose = defauts.get(cle) or defaut_final
        saisie = input(f"{label} [{propose}] : ").strip()
        return saisie or propose

    region = _demander("Région (ex: Extrême-Nord)", "region", "Extrême-Nord")
    delegation = _demander(
        "Délégation régionale (ex: Délégation Régionale de l'Extrême-Nord)",
        "delegation", f"Délégation Régionale de {region}"
    )
    etablissement = _demander("Nom de l'établissement (ex: Lycée Classique de Maroua)", "etablissement", "Établissement")
    annee_scolaire = _demander("Année scolaire (ex: 2025-2026)", "annee_scolaire", "2025-2026")
    duree = _demander("Durée de l'épreuve (ex: 3 heures)", "duree", "3 heures")
    coefficient = _demander("Coefficient (ex: 7)", "coefficient", "7")
    bilingue = input("Version bilingue français/anglais dans l'en-tête ? (o/n) [o] : ").strip().lower()
    bilingue = bilingue != "n"

    return {
        "region": region,
        "delegation": delegation,
        "etablissement": etablissement,
        "annee_scolaire": annee_scolaire,
        "duree": duree,
        "coefficient": coefficient,
        "bilingue": bilingue,
    }


def confirmer_champs_entete(champs: list[dict]) -> list[dict]:
    """UNIQUEMENT CLI. Présente chaque champ trouvé par
    extraire_entete_personnalisable.py et laisse le prof garder ou
    modifier la valeur -- 'ça demande et ça confirme', un champ à la
    fois, exactement le flux demandé.

    Retourne la même liste enrichie de 'valeur_finale' (== 'valeur'
    d'origine si non modifiée), prête pour personnaliser_entete_image().
    Prévient explicitement le prof quand un champ n'a pas de position
    connue -- dans ce cas son édition ne sera pas visible dans l'image,
    même s'il tape une nouvelle valeur ici (elle sert alors uniquement
    au contexte de génération, pas à l'en-tête visuel)."""
    print("\n" + "═" * 60)
    print("CHAMPS DÉTECTÉS DANS L'EN-TÊTE -- confirme ou modifie chacun")
    print("═" * 60)

    champs_confirmes = []
    for champ in champs:
        avertissement = "" if champ.get("boite") else "  (position non détectée -- non modifiable visuellement)"
        saisie = input(f"{champ['label']} [{champ['valeur']}]{avertissement} : ").strip()
        champs_confirmes.append({
            "label": champ["label"],
            "valeur_originale": champ["valeur"],
            "valeur_finale": saisie or champ["valeur"],
            "boite": champ.get("boite"),
        })
    return champs_confirmes


def extraire_contexte_regional(champs_confirmes: list[dict]) -> dict:
    """Cherche, parmi les champs confirmés, ceux qui ressemblent à
    'région' ou 'classe' (labels dynamiques, pas de clé fixe garantie)
    -- pour alimenter le contexte de la Partie Compétences dans
    construire_prompt(), comme avant. Recherche insensible à la casse
    sur le label, pas sur une clé attendue à l'avance."""
    contexte = {}
    for champ in champs_confirmes:
        label_bas = champ["label"].lower()
        if "region" in label_bas or "région" in label_bas:
            contexte["region"] = champ["valeur_finale"]
        elif "classe" in label_bas:
            contexte["classe"] = champ["valeur_finale"]
    return contexte


def preparer_entete_depuis_upload(chemin_fichier: Path) -> tuple[str, dict]:
    """Flux complet upload -> confirmation -> image personnalisée.

    Retourne (chemin_image_entete_finale, contexte_regional). Si
    l'extraction échoue (document illisible, API indisponible...),
    lève ExtractionEnteteEchouee -- c'est à l'appelant (main()) de
    basculer sur la saisie manuelle complète plutôt que de bloquer."""
    image_page, fraction, champs, confiance = extraire_entete(chemin_fichier)

    if confiance == "basse":
        print("⚠️  Confiance de lecture basse sur cet en-tête -- vérifie bien chaque champ proposé.")

    if not champs:
        print("⚠️  Aucun champ variable détecté avec confiance dans cet en-tête.")
        print("   L'image sera utilisée telle quelle, sans personnalisation possible.")
        champs_confirmes = []
    else:
        champs_confirmes = confirmer_champs_entete(champs)

    image_personnalisee = personnaliser_entete_image(image_page, champs_confirmes)
    image_decoupee = decouper_a_la_fraction(image_personnalisee, fraction)

    DOSSIER_ENTETES_FINALES.mkdir(parents=True, exist_ok=True)
    chemin_sortie = DOSSIER_ENTETES_FINALES / f"entete_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    image_decoupee.save(chemin_sortie, format="PNG")

    return str(chemin_sortie), extraire_contexte_regional(champs_confirmes)


def construire_prompt(sequence: int, themes_freq: list, baremes: dict, exemples: list[str],
                       metadonnees: dict | None = None, type_document: str = "Sequence",
                       serie: str | None = None) -> str:
    """N'a plus besoin de décrire le schéma JSON en texte -- c'est
    response_schema qui s'en charge (voir schema_epreuve.py). Le
    prompt se concentre sur le contenu pédagogique attendu.

    `metadonnees` (optionnel) : dict de contexte réel de l'établissement
    (région, classe, année scolaire...) -- utilisé UNIQUEMENT pour
    ancrer la situation-problème de la Partie Compétences dans un cadre
    local plausible. Le nom exact de l'établissement n'est jamais
    injecté dans le contenu généré : il n'est fiable que dans l'en-tête
    (recopié tel quel depuis l'extraction), pas comme donnée que le
    modèle doit reformuler correctement dans une phrase.

    `type_document` : 'Sequence' (défaut, comportement inchangé) ou
    'Examen' -- dans ce second cas, `serie` est obligatoire (imposé
    par l'appelant, voir generer_epreuve_json()) et un bloc de
    contraintes supplémentaires est ajouté au prompt : coefficient,
    durée, et règle stricte sur serie_applicable des questions.

    FIX du 23/08/2026 : la répartition du barème (ressources /
    compétences / présentation) est maintenant calculée en Python via
    calculer_repartition_bareme() et injectée comme contrainte
    chiffrée EXACTE -- plus jamais comme moyenne indicative que le
    modèle pouvait réinterpréter sans jamais vérifier que la somme
    globale retombe sur 20."""
    themes_texte = "\n".join(f"  - {nom} (observé {freq} fois)" for nom, freq in themes_freq[:10])

    type_document_bd = "examen" if type_document == "Examen" else "sequence"
    repartition = calculer_repartition_bareme(baremes, type_document_bd)
    bareme_ressources = repartition["ressources"]
    bareme_competences = repartition["competences"]
    presentation_pts = repartition["presentation"]

    bareme_texte = (
        f"RÉPARTITION OBLIGATOIRE DU BARÈME (total = {BAREME_TOTAL:g} points, AUCUNE tolérance) :\n"
        f"  - Partie A (Ressources), champ bareme_points = EXACTEMENT {bareme_ressources:g}\n"
        f"  - Partie B (Compétences), champ bareme_points = EXACTEMENT {bareme_competences:g}\n"
        f"  - presentation_points = EXACTEMENT {presentation_pts:g}\n"
        f"  Vérification : {bareme_ressources:g} + {bareme_competences:g} + {presentation_pts:g} "
        f"= {bareme_ressources + bareme_competences + presentation_pts:g}\n"
        f"Ces trois nombres sont des CONTRAINTES DURES, pas des indications approximatives -- "
        f"ne choisis pas d'autres valeurs même si les exemples de style ci-dessous suggèrent "
        f"une répartition différente.\n"
        f"La somme des bareme_points de tous les exercices de la Partie A doit faire "
        f"EXACTEMENT {bareme_ressources:g}.\n"
        f"La somme des bareme des tâches de la Partie B doit faire EXACTEMENT {bareme_competences:g}."
    )

    exemples_texte = "\n\n".join(
        f"--- EXEMPLE DE STYLE {i+1} (NE PAS recopier, juste s'en inspirer -- IGNORE le barème "
        f"de cet exemple, seule la répartition chiffrée ci-dessus fait foi) ---\n{ex}"
        for i, ex in enumerate(exemples)
    )

    metadonnees = metadonnees or {}
    champs_reels = {k: v for k, v in metadonnees.items() if k in ("region", "classe") and v}
    contexte_reel = ""
    if champs_reels:
        lignes = "\n".join(f"  - {k} : {v}" for k, v in champs_reels.items())
        contexte_reel = f"""
CONTEXTE RÉEL (utilise UNIQUEMENT pour ancrer la situation-problème de la Partie \
Compétences dans un cadre local plausible -- ex: une activité économique réaliste pour \
cette région -- JAMAIS pour changer une donnée mathématique, et JAMAIS pour mentionner \
le nom d'un établissement dans l'énoncé) :
{lignes}
"""

    # ═══════════════════════════════════════════════════════
    # Bloc spécifique Examen officiel -- absent du prompt tant que
    # type_document == "Sequence", donc zéro impact sur le
    # comportement existant.
    # ═══════════════════════════════════════════════════════
    bloc_examen = ""
    if type_document == "Examen":
        coefficient = COEFFICIENT_EXAMEN[serie]
        bloc_examen = f"""
CONTEXTE EXAMEN OFFICIEL (Baccalauréat MINESEC) :
- Cette épreuve est un vrai sujet d'EXAMEN OFFICIEL, pas une évaluation de séquence
  interne -- niveau d'exigence et de couverture du programme correspondants (l'épreuve
  couvre l'ensemble du programme de Terminale C, pas une séquence isolée).
- type_document DOIT valoir exactement "Examen" (recopie cette valeur telle quelle).
- sequence DOIT valoir 0 (sans objet pour un Examen).
- Série concernée : {serie}. Coefficient officiel : {coefficient}. Durée : {DUREE_EXAMEN}.
- RÈGLE SERIE_APPLICABLE : le champ serie_applicable de CHAQUE question doit valoir
  "toutes" SAUF si le contenu mathématique de cette question est explicitement réservé
  à la série {serie} (auquel cas serie_applicable="{serie}"). N'introduis PAS de
  question réservée à l'autre série ({"E" if serie == "C" else "C"}) -- elle n'aurait
  aucun sens dans une épreuve destinée à la série {serie} et sera rejetée par le
  validateur.
- La quasi-totalité des questions doivent rester "toutes" -- ne réserve une question à
  la série {serie} que si c'est mathématiquement justifié (ex: une notion au programme
  de spécialité C mais pas E), pas par défaut.
"""

    regles_strictes = f"""
RÈGLES ABSOLUES DE FORMAT — CES RÈGLES SONT PLUS IMPORTANTES QUE LES EXEMPLES DE STYLE :

1. LATEX :
   - Toute commande LaTeX commençant par un antislash (\\frac, \\sqrt, \\leq,
     \\geq, \\in, \\neq, \\equiv, \\mathbb, etc.) DOIT être entièrement
     placée entre $ et $.
   - Exemple CORRECT : "tel que $2-u_n\\leq 2$ puis $2-u_n\\leq10^{-3}$."
   - Exemple INCORRECT : "tel que $2-u_n$\\leq$2$" ou "tel que
     $2-u_n$ \\leq $10^{-3}$".
   - N'utilise JAMAIS \\left ni \\right. Utilise uniquement les parenthèses
     et crochets normaux ( ) [ ].
   - N'utilise JAMAIS \\begin, \\end, \\array, \\substack ou \\pmod.
   - Pour une congruence, écris par exemple $a \\equiv 3$ (mod 5), avec
     (mod 5) hors des dollars.
   - N'écris JAMAIS de commande LaTeX hors d'un bloc $...$.
   - Les exemples de style peuvent contenir du LaTeX interdit ou mal encadré :
     NE LES RECOPIE PAS. Seules les règles ci-dessus font foi.

2. STRUCTURE OBLIGATOIRE :
   - La liste `parties` contient EXACTEMENT deux parties et dans cet ordre :
     ressources puis competences.
   - La partie ressources possède obligatoirement une liste `exercices` NON VIDE.
   - Chaque exercice possède obligatoirement une liste `questions` NON VIDE.
   - La partie compétences possède obligatoirement une liste `taches` NON VIDE,
     avec exactement 2 ou 3 tâches.
   - Chaque tâche possède obligatoirement un champ `bareme` strictement positif.
   - Ne laisse JAMAIS `taches` à null ou vide.

3. BARÈME — VALEURS EXACTES :
   - Partie A `bareme_points` = EXACTEMENT {bareme_ressources}.
   - Partie B `bareme_points` = EXACTEMENT {bareme_competences}.
   - `presentation_points` = EXACTEMENT {presentation_pts}.
   - Chaque exercice : `bareme_points` = somme EXACTE de ses `questions[].bareme`.
   - La somme des exercices de la Partie A = EXACTEMENT {bareme_ressources}.
   - La somme des tâches de la Partie B = EXACTEMENT {bareme_competences}.
   - Le total général = {bareme_ressources} + {bareme_competences} + {presentation_pts}
     = EXACTEMENT 20.
   - Avant de répondre, fais le calcul des sommes toi-même et corrige toute
     incohérence. Ne fournis jamais une partie dont le barème est annoncé mais
     dont les sous-éléments ont un total différent.

4. VALIDATION FINALE OBLIGATOIRE :
   - Relis chaque texte et cherche visuellement chaque antislash `\\`.
   - Si un `\\` est suivi d'une commande LaTeX, vérifie qu'il se trouve entre $...$.
   - Vérifie qu'il n'existe aucun `\\left` ou `\\right`.
   - Vérifie que chaque tâche de la Partie B a un `bareme` numérique et que leur
     somme vaut EXACTEMENT {bareme_competences}.
"""

    intro = (
        f"Tu es un examinateur agréé MINESEC, membre du jury du Baccalauréat, "
        f"spécialiste du programme de Terminale C."
        if type_document == "Examen" else
        f"Tu es un professeur de mathématiques camerounais expérimenté, correcteur "
        f"agréé MINESEC, spécialiste du programme de Terminale C."
    )

    tache_principale = (
        f"TÂCHE : Génère un sujet d'EXAMEN OFFICIEL (Baccalauréat) ENTIÈREMENT INÉDIT, "
        f"série {serie}, style MINESEC/APC."
        if type_document == "Examen" else
        f"TÂCHE : Génère une épreuve ENTIÈREMENT INÉDITE pour la {sequence}e séquence, "
        f"style MINESEC/APC."
    )

    return f"""{intro}

{regles_strictes}
{bloc_examen}
{tache_principale}
{contexte_reel}
{bareme_texte}

DONNÉES RÉELLES OBSERVÉES :
Thèmes dominants :
{themes_texte}

{exemples_texte}

CONSIGNES :
- Structure : Ressources (3-4 exercices indépendants) + Compétences (1 situation-problème).
- GRANULARITÉ OBLIGATOIRE : chaque exercice doit être découpé en PLUSIEURS petites \
  sous-questions (5 à 9 par exercice selon son barème total), jamais 2 ou 3 grosses \
  questions. Une sous-question vaut typiquement entre 0,25 et 1 point -- jamais plus de \
  1,5 point. Si une étape de raisonnement peut être scindée en deux (ex: "calculer" puis \
  "en déduire"), scinde-la en deux sous-questions numérotées séparément.
- Utilise la numérotation par lettres pour les sous-parties d'une même question \
  (1.a), 1.b), 1.c)...) exactement comme un examinateur MINESEC le ferait.
- INTERDICTION de recopier un énoncé, contexte ou valeur numérique des exemples -- \
  invente entièrement.
- Utilise en priorité les thèmes les plus fréquents listés ci-dessus.
- Varie les exercices : évite les grands classiques trop récurrents (ex: le cercle \
  "z-2i/z+1 imaginaire pur" est TRÈS surexploité, ne le réutilise pas).
- Vérifie la cohérence mathématique de chaque question AVANT de répondre (pas de \
  contexte ou d'hypothèse qui rendrait l'exercice faux ou insoluble).
- La Partie Compétences doit rester UNE situation cohérente : les 2-3 tâches doivent \
  réutiliser une variable ou un résultat commun issu du contexte, pas trois calculs \
  indépendants juste habillés du même personnage.
- AVANT de répondre, vérifie toi-même que la somme des bareme_points respecte \
  exactement la répartition obligatoire donnée plus haut -- si ce n'est pas le cas, \
  ajuste le nombre ou le poids des sous-questions jusqu'à ce que ça tombe juste.

N'écris AUCUN commentaire, note, ou justification en dehors des champs du schéma -- \
uniquement le contenu de l'épreuve elle-même."""


def parser_reponse(response) -> dict:
    """Avec response_schema, le SDK expose response.parsed (instance
    Pydantic déjà validée structurellement). On l'utilise en priorité
    -- json.loads(response.text) reste un filet de secours si jamais
    cette version du SDK ne peuple pas .parsed."""
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        return parsed.model_dump()
    if not response.text:
        raise ValueError("Réponse vide de Gemini (probablement tronquée).")
    return json.loads(response.text)


def generer_epreuve_json(sequence: int, metadonnees: dict, modele: str = MODELE_PAR_DEFAUT,
                          contexte_regional: dict | None = None, type_document: str = "Sequence",
                          serie: str | None = None) -> Path:
    """
    Version appelable directement (utilisée par la route Flask du
    générateur). Ne fait AUCUN input().

    `type_document` : "Sequence" (défaut, comportement identique à
    avant cette extension) ou "Examen". Pour "Examen", `serie` est
    OBLIGATOIRE ("C" ou "E") -- RuntimeError explicite sinon (fail
    loudly plutôt que deviner une série par défaut, qui changerait le
    coefficient et donc l'en-tête officiel sans que personne ne
    s'en aperçoive). Pour "Sequence", `serie` est ignoré s'il est
    fourni par erreur.

    `sequence` : obligatoire et significatif uniquement pour
    type_document="Sequence" (1 à 6, voir SEQUENCES_SUPPORTEES). Pour
    "Examen", cette valeur n'est pas utilisée pour interroger rag.db
    (voir calculer_frequence_themes) -- passer 0 par convention.

    Lève une exception (RuntimeError) en cas d'échec définitif, avec
    le détail des problèmes de validation rencontrés sur la dernière
    tentative -- utile pour debugger un prompt qui dérive.

    Retourne le chemin du fichier JSON écrit -- UNIQUEMENT du contenu
    qui a passé la validation.

    Aucune validation de `sequence` codée en dur ici à dessein pour le
    mode Séquence : la requête SQL sur rag.db tranche d'elle-même s'il
    existe des données pour ce numéro (RuntimeError explicite sinon,
    voir plus bas). La liste SEQUENCES_SUPPORTEES ne sert qu'à la
    validation d'entrée côté CLI (main()) et côté route Flask (app.py).
    """
    if type_document not in ("Sequence", "Examen"):
        raise RuntimeError(f"type_document invalide : {type_document!r} (attendu 'Sequence' ou 'Examen').")

    if type_document == "Examen":
        if serie not in SERIES_SUPPORTEES:
            raise RuntimeError(
                f"Une série ('C' ou 'E') est obligatoire pour générer un Examen officiel, "
                f"reçu : {serie!r}. Impossible de deviner un coefficient/une durée par défaut."
            )

    if not DB_PATH.exists():
        raise RuntimeError(f"Base introuvable : {DB_PATH}")

    # Construit un client par clé API disponible (voir
    # gemini_client.CLES_API_ENV) -- lève RuntimeError immédiatement
    # si aucune clé n'est trouvée, avant de gaspiller du temps à
    # interroger la base.
    clients = construire_clients()

    type_document_bd = "examen" if type_document == "Examen" else "sequence"

    conn = sqlite3.connect(DB_PATH)
    themes_freq = calculer_frequence_themes(conn, sequence, type_document_bd)
    if not themes_freq:
        conn.close()
        cible = "les Examens officiels" if type_document == "Examen" else f"la séquence {sequence}"
        raise RuntimeError(f"Aucune donnée structurée pour {cible}.")
    baremes = calculer_bareme_moyen(conn, sequence, type_document_bd)
    exemples = selectionner_exemples_style(conn, sequence, NB_EXEMPLES_STYLE, type_document_bd)
    conn.close()

    prompt = construire_prompt(sequence, themes_freq, baremes, exemples, contexte_regional,
                                type_document=type_document, serie=serie)

    config_kwargs = dict(
        response_mime_type="application/json",
        response_schema=EpreuveGeneree,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    try:
        config = types.GenerateContentConfig(
            **config_kwargs,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        )
    except (AttributeError, TypeError):
        config = types.GenerateContentConfig(**config_kwargs)

    contenu_json = None
    derniere_erreur = None
    derniers_problemes_validation = []

    # Répartition calculée en Python, dans la portée de la boucle.
    # Ces valeurs servent au feedback injecté après une validation échouée.
    repartition = calculer_repartition_bareme(baremes, type_document_bd)
    bareme_ressources = repartition["ressources"]
    bareme_competences = repartition["competences"]

    # serie_demandee n'est passé au validateur QUE pour un Examen --
    # voir detecter_serie_incorrecte() dans valider_epreuve.py, qui
    # n'a de sens que dans ce contexte.
    serie_demandee = serie if type_document == "Examen" else None

    prompt_tentative = prompt

    for tentative, pause in enumerate(PAUSES_ENTRE_TENTATIVES[:NB_TENTATIVES_MAX], start=1):
        if pause:
            time.sleep(pause)

        try:
            response, modele_utilise, cle_utilisee = generer_avec_fallback(
                clients,
                prompt_tentative,
                config,
            )
            candidat = parser_reponse(response)
        except (json.JSONDecodeError, ValueError) as e:
            derniere_erreur = f"Réponse invalide (tentative {tentative}) : {e}"
            continue
        except Exception as e:
            derniere_erreur = f"Erreur réseau/API (tentative {tentative}) : {e}"
            continue

        ok, problemes = valider_epreuve_generee(candidat, serie_demandee=serie_demandee)
        if ok:
            contenu_json = candidat
            break

        derniers_problemes_validation = problemes
        derniere_erreur = (
            f"Validation échouée (tentative {tentative}), {len(problemes)} problème(s) : "
            + " | ".join(problemes[:5])
        )

        # Les tentatives suivantes reçoivent les erreurs EXACTES du validateur.
        # On ne répète donc pas aveuglément le même prompt après un échec.
        problemes_feedback = "\n".join(f"  - {p}" for p in problemes[:10])
        rappel_serie = (
            f"- aucune question n'a de serie_applicable incompatible avec la série {serie} ;\n"
            if serie_demandee else ""
        )
        prompt_tentative = prompt + f"""

RAPPEL DE VALIDATION — TENTATIVE PRÉCÉDENTE REJETÉE :
Les erreurs ci-dessous ont été détectées par le validateur. Tu dois les corriger
dans la nouvelle génération. Ne les reproduis sous aucune forme :

{problemes_feedback}

AVANT DE RÉPONDRE, vérifie particulièrement :
- toutes les commandes LaTeX sont entre $...$ ;
- aucune occurrence de \\left ou \\right ;
- la Partie Compétences contient 2 ou 3 tâches avec un `bareme` numérique ;
- la somme des bareme des tâches = EXACTEMENT {bareme_competences} ;
- la somme des exercices de la Partie A = EXACTEMENT {bareme_ressources} ;
- le total général avec presentation_points = EXACTEMENT 20 ;
{rappel_serie}"""

    if contenu_json is None:
        detail = "\n  - ".join(derniers_problemes_validation) if derniers_problemes_validation else "(aucun détail)"
        raise RuntimeError(
            f"Échec de la génération après {NB_TENTATIVES_MAX} tentatives.\n"
            f"Dernière erreur : {derniere_erreur}\n"
            f"Derniers problèmes de validation :\n  - {detail}"
        )

    # Métadonnées d'en-tête enrichies pour un Examen -- coefficient et
    # durée officiels, jamais laissés à une valeur par défaut générique
    # de séquence. Ne modifie rien pour type_document="Sequence" : ces
    # clés ne sont ajoutées que dans le cas Examen.
    if type_document == "Examen":
        metadonnees = dict(metadonnees)  # copie -- ne mute pas l'argument reçu
        metadonnees.setdefault("serie", serie)
        metadonnees.setdefault("coefficient", str(COEFFICIENT_EXAMEN[serie]))
        metadonnees.setdefault("duree", DUREE_EXAMEN)

    paquet_final = {
        "metadonnees": metadonnees,
        "contenu": contenu_json,
        "genere_le": datetime.now().isoformat(timespec="seconds"),
    }

    SORTIE_DIR.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffixe = f"examen_{serie}" if type_document == "Examen" else f"seq{sequence}"
    chemin_sortie = SORTIE_DIR / f"epreuve_{suffixe}_{horodatage}.json"
    chemin_sortie.write_text(json.dumps(paquet_final, ensure_ascii=False, indent=2), encoding="utf-8")

    return chemin_sortie


def main():
    parser = argparse.ArgumentParser(description="Génère une épreuve en JSON structuré via Gemini (schéma contraint)")
    # MISE A JOUR (24/08/2026) : 5 et 6 ajoutées à la liste des choix valides.
    parser.add_argument("--sequence", type=int, choices=SEQUENCES_SUPPORTEES,
                         help="Numéro de séquence -- requis si --type=sequence (défaut).")
    parser.add_argument("--type", dest="type_document", choices=["sequence", "examen"], default="sequence",
                         help="'sequence' (défaut) ou 'examen' pour un sujet de Baccalauréat officiel.")
    parser.add_argument("--serie", choices=SERIES_SUPPORTEES, default=None,
                         help="Série ('C' ou 'E') -- requis si --type=examen.")
    parser.add_argument("--modele", default=MODELE_PAR_DEFAUT)
    parser.add_argument("--entete", type=Path, default=None,
                         help="Chemin d'une vraie épreuve (photo/scan/PDF) à utiliser comme "
                              "en-tête -- logo et mise en page conservés, valeurs personnalisables.")
    args = parser.parse_args()

    type_document = "Examen" if args.type_document == "examen" else "Sequence"

    if type_document == "Sequence" and args.sequence is None:
        parser.error("--sequence est requis quand --type=sequence (ou par défaut).")
    if type_document == "Examen" and args.serie is None:
        parser.error("--serie est requis quand --type=examen.")

    contexte_regional = {}
    chemin_image_entete = None

    if args.entete:
        print(f"📷 Extraction de l'en-tête depuis {args.entete}...\n")
        try:
            chemin_image_entete, contexte_regional = preparer_entete_depuis_upload(args.entete)
            print(f"\n✅ En-tête personnalisé prêt : {chemin_image_entete}\n")
        except ExtractionEnteteEchouee as e:
            print(f"⚠️  Extraction de l'en-tête échouée ({e}) -- passage en saisie manuelle complète.\n")

    if chemin_image_entete:
        # En-tête déjà personnalisé depuis l'image -- pas besoin de
        # redemander région/établissement/année en texte, ce serait
        # redondant avec ce qui vient d'être confirmé champ par champ.
        metadonnees = {"chemin_image_entete": chemin_image_entete}
    else:
        metadonnees = demander_metadonnees_utilisateur()

    print("\n🧠 Génération en cours (peut prendre 20-40s, jusqu'à 3 tentatives si validation échoue)...\n")

    try:
        chemin_sortie = generer_epreuve_json(
            args.sequence or 0, metadonnees, args.modele, contexte_regional,
            type_document=type_document, serie=args.serie,
        )
    except RuntimeError as e:
        print(f"❌ {e}")
        return

    print(f"✅ Épreuve générée (JSON validé) : {chemin_sortie}")
    print("   Prochaine étape : python construire_pdf_officiel.py --fichier "
          f"\"{chemin_sortie}\"")


if __name__ == "__main__":
    main()