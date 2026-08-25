# scripts/extraire_structure_gemini.py
"""
ÉTAPE 3b du pipeline RAG Maths Terminale C -- VERSION GEMINI (GRATUITE).

MISE A JOUR : filtre étendu aux séquences 1 à 6 (avant : 1-4 seulement)
pour permettre la génération sur toutes les séquences.

FIX (25/08/2026) -- GEMINI_API_KEY manquant alors qu'il est bien dans
.env : ce script est lancé directement en CLI
(`python scripts/extraire_structure_gemini.py`), pas via app.py --
donc le load_dotenv() fait au démarrage de Flask ne s'applique jamais
ici. os.environ.get() ne voit alors que les vraies variables
d'environnement du shell, pas le contenu de .env. Chaque script CLI
autonome doit charger .env lui-même, il ne peut jamais compter sur le
fait qu'un autre processus (app.py) l'ait déjà fait avant lui.

Nécessite : pip install -U google-genai python-dotenv
Nécessite : la variable d'environnement GEMINI_API_KEY (dans .env ou
            définie manuellement dans le shell)

Usage :
    python extraire_structure_gemini.py                # tout traiter
    python extraire_structure_gemini.py --limite 3      # test sur 3
"""

import os
import re
import json
import time
import sqlite3
import argparse
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types

DB_PATH = Path("data/rag_maths_bac_c/rag.db")
MODELE_GEMINI = "gemini-3.6-flash"
PAUSE_ENTRE_APPELS = 6
LIMITE_CARACTERES_TEXTE = 20000

THEMES_TEXTE = """1. Calcul vectoriel et produit vectoriel
2. Espace vectoriel et application linéaire
3. Division euclidienne dans Z et congruences
4. Arithmétique : PGCD, PPCM et nombres premiers
5. Nombres complexes : approche algébrique
6. Nombres complexes : approche géométrique
7. Isométries de l'espace
8. Statistiques
9. Primitives d'une fonction continue sur un intervalle
10. Fonctions exponentielles et puissances
11. Calcul intégral
12. Équations différentielles
13. Suites numériques
14. Théorie des graphes
15. Coniques
16. Similitudes directes planes
17. Fonctions numériques d'une variable réelle
18. Fonction logarithme népérien
19. Probabilités"""

PROMPT_SYSTEME = f"""Tu es un professeur de mathématiques camerounais expérimenté, \
correcteur agréé MINESEC, spécialiste du programme de Terminale C.

On te donne le texte brut d'une épreuve de mathématiques (extrait automatiquement \
d'un PDF -- il peut contenir des artefacts de mise en forme, des en-têtes \
d'établissement, des filigranes, etc. à ignorer).

Les épreuves de Terminale C suivent la structure APC (Approche Par Compétences) \
du MINESEC :
- Une partie "Évaluation des Ressources" (généralement ~15 points) : plusieurs \
  exercices indépendants testant des savoir-faire techniques.
- Une partie "Évaluation des Compétences" (généralement ~4,5 à 5 points) : UNE \
  situation-problème complexe mobilisant plusieurs notions ensemble.
- Parfois une note de "Présentation" séparée (~0,5 point), transversale, non liée \
  à un exercice précis.

Les barèmes réels varient selon l'établissement -- extrais toujours les valeurs \
RÉELLEMENT visibles dans le texte, ne suppose jamais les valeurs standards si \
le texte donne autre chose.

Voici la liste FERMÉE des 19 thèmes du programme officiel. Pour chaque exercice, \
tu dois choisir UNIQUEMENT parmi ces numéros (un exercice peut avoir plusieurs \
thèmes, car les exercices mélangent souvent plusieurs notions) :

{THEMES_TEXTE}

Réponds UNIQUEMENT avec un objet JSON valide, sans aucun texte avant ou après, \
sans balises markdown, selon ce schéma exact :

{{
  "bareme_total": <nombre ou null>,
  "structure_atypique": <true si l'épreuve ne suit PAS le format Ressources/Compétences, false sinon>,
  "parties": [
    {{
      "type_partie": "ressources" | "competences" | "presentation",
      "bareme_points": <nombre ou null>,
      "exercices": [
        {{
          "numero_exercice": <entier ou null>,
          "bareme_points": <nombre ou null>,
          "nombre_questions": <entier ou null>,
          "themes": [<numéros de 1 à 19>]
        }}
      ]
    }}
  ]
}}"""


def nettoyer_reponse_json(texte_reponse: str) -> str:
    texte = texte_reponse.strip()
    texte = re.sub(r'^```(?:json)?\s*', '', texte)
    texte = re.sub(r'\s*```$', '', texte)
    return texte.strip()


def extraire_structure(client, modele, texte_epreuve):
    texte_tronque = texte_epreuve[:LIMITE_CARACTERES_TEXTE]
    try:
        config = types.GenerateContentConfig(
            system_instruction=PROMPT_SYSTEME,
            response_mime_type="application/json",
            max_output_tokens=8000,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        )
    except (AttributeError, TypeError):
        config = types.GenerateContentConfig(
            system_instruction=PROMPT_SYSTEME,
            response_mime_type="application/json",
            max_output_tokens=8000,
        )

    response = client.models.generate_content(
        model=modele,
        contents="\n\n--- ÉPREUVE À ANALYSER ---\n\n" + texte_tronque,
        config=config,
    )

    texte_reponse = response.text
    if texte_reponse is None:
        raise ValueError(
            f"Réponse vide (probablement tronquée -- finish_reason="
            f"{response.candidates[0].finish_reason if response.candidates else '?'})"
        )
    texte_json = nettoyer_reponse_json(texte_reponse)
    structure = json.loads(texte_json)

    try:
        tok_in = response.usage_metadata.prompt_token_count
        tok_out = response.usage_metadata.candidates_token_count
    except AttributeError:
        tok_in, tok_out = None, None

    return structure, tok_in, tok_out


def valider_et_inserer(conn, epreuve_id, structure):
    bareme_total = structure.get("bareme_total")
    conn.execute(
        "UPDATE epreuves SET bareme_total = ? WHERE id = ?",
        (bareme_total, epreuve_id)
    )

    for partie in structure.get("parties", []):
        cur = conn.execute("""
            INSERT INTO parties (epreuve_id, type_partie, bareme_points)
            VALUES (?, ?, ?)
        """, (epreuve_id, partie.get("type_partie"), partie.get("bareme_points")))
        partie_id = cur.lastrowid

        for exercice in partie.get("exercices", []):
            cur = conn.execute("""
                INSERT INTO exercices (partie_id, numero_exercice, bareme_points, nombre_questions)
                VALUES (?, ?, ?, ?)
            """, (
                partie_id,
                exercice.get("numero_exercice"),
                exercice.get("bareme_points"),
                exercice.get("nombre_questions"),
            ))
            exercice_id = cur.lastrowid

            themes_bruts = exercice.get("themes", [])
            themes_valides = [t for t in themes_bruts if isinstance(t, int) and 1 <= t <= 19]
            if len(themes_valides) != len(themes_bruts):
                print(f"    ⚠️ Thème(s) hors référentiel ignoré(s) : {themes_bruts}")

            for theme_id in themes_valides:
                conn.execute("""
                    INSERT OR IGNORE INTO exercice_themes (exercice_id, theme_id)
                    VALUES (?, ?)
                """, (exercice_id, theme_id))


def main():
    parser = argparse.ArgumentParser(description="Extraction structurée par Gemini (gratuit) — étape 3")
    parser.add_argument("--limite", type=int, default=None,
                         help="Limite le nombre d'épreuves traitées (pour tester)")
    parser.add_argument("--modele", default=MODELE_GEMINI,
                         help=f"ID du modèle Gemini (défaut: {MODELE_GEMINI})")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ Variable d'environnement GEMINI_API_KEY manquante.")
        print("   Vérifie que ton fichier .env (à la racine du projet, à côté de app.py)")
        print("   contient bien une ligne : GEMINI_API_KEY=ta-clé")
        print("   (pas de guillemets, pas d'espace autour du =, format .env pur -- pas la")
        print("   syntaxe PowerShell $env:... qui a déjà causé un bug par le passé).")
        print("   Windows (PowerShell), en dépannage ponctuel sans toucher .env :")
        print("   $env:GEMINI_API_KEY = 'ta-clé'")
        return

    if not DB_PATH.exists():
        print(f"❌ Base introuvable : {DB_PATH}")
        return

    client = genai.Client(api_key=api_key)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    # MODIFIÉ : sequence IN (1,2,3,4) -> (1,2,3,4,5,6)
    query = """
        SELECT id, titre_original, texte_extrait FROM epreuves
        WHERE type_document = 'sequence'
          AND matiere_suspecte = 0
          AND statut_extraction = 'ok'
          AND sequence IN (1, 2, 3, 4, 5, 6)
          AND (statut_structuration = 'non_traite' 
               OR statut_structuration IS NULL
               OR statut_structuration IN ('echec_api', 'echec_json'))
        ORDER BY id
    """
    if args.limite:
        query += f" LIMIT {args.limite}"

    lignes = conn.execute(query).fetchall()
    print(f"🧠 {len(lignes)} épreuve(s) à structurer avec Gemini ({args.modele})...")
    print(f"   Pause de {PAUSE_ENTRE_APPELS}s entre chaque appel (respect du quota gratuit)\n")

    compteur_ok = 0
    compteur_echec = 0

    for id_, titre, texte in lignes:
        print(f"  → [ID {id_}] {titre[:70]}")
        try:
            structure, tok_in, tok_out = extraire_structure(client, args.modele, texte)
            valider_et_inserer(conn, id_, structure)
            conn.execute(
                "UPDATE epreuves SET statut_structuration = 'ok' WHERE id = ?",
                (id_,)
            )
            conn.commit()
            compteur_ok += 1
            nb_parties = len(structure.get("parties", []))
            info_tokens = f"({tok_in} tok entrée / {tok_out} tok sortie)" if tok_in else ""
            print(f"    ✅ {nb_parties} partie(s) extraite(s) {info_tokens}")

        except json.JSONDecodeError as e:
            print(f"    ❌ Réponse JSON invalide : {e}")
            conn.execute(
                "UPDATE epreuves SET statut_structuration = 'echec_json' WHERE id = ?",
                (id_,)
            )
            conn.commit()
            compteur_echec += 1

        except Exception as e:
            print(f"    ❌ Erreur : {e}")
            erreur_str = str(e)
            if "429" in erreur_str or "RESOURCE_EXHAUSTED" in erreur_str or "quota" in erreur_str.lower():
                print("    ⏳ Quota atteint, pause de 60s avant de continuer...")
                time.sleep(60)
            elif "503" in erreur_str or "UNAVAILABLE" in erreur_str:
                print("    ⏳ Service temporairement surchargé (503)...")
                reussi_apres_retry = False
                for tentative, pause in enumerate([15, 30, 60], start=1):
                    print(f"    🔁 Nouvelle tentative {tentative}/3 dans {pause}s...")
                    time.sleep(pause)
                    try:
                        structure, tok_in, tok_out = extraire_structure(client, args.modele, texte)
                        valider_et_inserer(conn, id_, structure)
                        conn.execute(
                            "UPDATE epreuves SET statut_structuration = 'ok' WHERE id = ?",
                            (id_,)
                        )
                        conn.commit()
                        compteur_ok += 1
                        nb_parties = len(structure.get("parties", []))
                        print(f"    ✅ Réussi après retry : {nb_parties} partie(s) extraite(s)")
                        reussi_apres_retry = True
                        break
                    except Exception as e2:
                        print(f"    ❌ Retry {tentative} échoué : {e2}")
                if reussi_apres_retry:
                    time.sleep(PAUSE_ENTRE_APPELS)
                    continue
            conn.rollback()
            conn.execute(
                "UPDATE epreuves SET statut_structuration = 'echec_api' WHERE id = ?",
                (id_,)
            )
            conn.commit()
            compteur_echec += 1

        time.sleep(PAUSE_ENTRE_APPELS)

    conn.close()

    print("\n" + "═" * 50)
    print("BILAN DE L'EXTRACTION (GEMINI - GRATUIT)")
    print("═" * 50)
    print(f"  Réussies : {compteur_ok}")
    print(f"  Échecs   : {compteur_echec}")
    print("\nCoût : $0 (tier gratuit Gemini)")


if __name__ == "__main__":
    main()