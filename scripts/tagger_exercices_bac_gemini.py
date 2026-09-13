# scripts/tagger_exercices_bac_gemini.py
"""
Tagage one-shot (28/08/2026, etendu 12/09/2026) des sections reelles du
Bac (sections_bac_officielles) sur les lecons du referentiel APC (voir
importer_squelette_apc.py) -- PAS un tagage repete a chaque conversation
eleve, un script lance une fois par matiere/niveau/serie (puis relance
seulement si de nouvelles epreuves officielles sont importees).

GENERIQUE PAR MATIERE/NIVEAU/SERIE : --matiere determine le referentiel
de lecons utilise. Le niveau et la serie de chaque epreuve sont lus
directement depuis epreuves_bac_officielles (pas d'argument global pour
la serie, car elle varie d'une epreuve a l'autre au sein d'une meme
matiere/niveau -- ex: Physique Premiere existe en C, D et TI).

FILTRE PAR SERIE (essentiel) : la liste de lecons valides donnee a
Gemini est filtree sur la serie exacte de l'epreuve traitee. Sans ce
filtre, une matiere/niveau qui couvre plusieurs series (ex: Physique
Premiere C/D/TI) expose a Gemini des identifiants d'autres series
valides dans l'absolu mais faux pour cette epreuve precise -- constate
concretement (identifiants serie D retournes sur des epreuves serie C).

POURQUOI CE SCRIPT EXISTE : les fichiers de tagage fournis
(dataset_ia_correcteur_bac_strict.json, bac_epreuves_themes_corriges.json)
associent "Probabilites" a la quasi-totalite des questions, y compris
un exercice de recurrence sur la divisibilite et un exercice sur les
reflexions/isometries -- aucun rapport avec les probabilites dans les
deux cas. Tagage non fiable, constate sur plusieurs exemples reels
avant tout import (28/08/2026) -- jamais importe tel quel.

GARDE-FOUS DU PROMPT, contre ce mode d'echec precis :
  1. Liste FERMEE de lecons valides (matiere+niveau+serie de l'epreuve
     traitee) -- Gemini ne peut jamais inventer un identifiant,
     contrainte via response_schema (Pydantic), pas juste une
     instruction textuelle qu'il pourrait ignorer.
  2. Justification courte OBLIGATOIRE par tag, citant l'element
     precis (terme, notation, methode) -- decourage un tag "par
     reflexe" sans lien reel avec le contenu.
  3. Liste VIDE explicitement autorisee et encouragee en cas de doute
     -- "je ne sais pas" doit etre un resultat acceptable, jamais une
     lecon choisie par defaut.
  4. Validation POST-HOC systematique : tout identifiant retourne par
     Gemini qui n'existe pas reellement dans 'lecons' (pour cette
     matiere/niveau/serie) est rejete et logge, jamais insere en base.
  5. Matching des sections par POSITION, pas par nom retourne par
     Gemini -- constate que Gemini reformule parfois l'identifiant
     d'une section dans sa reponse (ex: colle le titre a
     l'identifiant : "Exercice 1 : Verification des savoirs / 8
     points" au lieu de "Exercice 1"), ce qui casse un matching par
     egalite stricte de chaine. Le prompt impose deja explicitement
     l'ordre des sections ; s'y fier est plus robuste. Si le nombre de
     sections retournees ne correspond pas au nombre attendu, les tags
     de cette epreuve sont abandonnes plutot que rattaches au hasard.

BATCH PAR EPREUVE (pas par section) : un appel Gemini par session,
chaque appel taguant toutes les sections de cette session en une
fois -- moins couteux en quota, et donne a Gemini le contexte complet
de l'epreuve pour mieux distinguer des sections proches.

COLLISION SESSION+MATIERE : deux niveaux differents (ex: Physique
Terminale et Premiere) peuvent partager la meme annee. Toute recherche
d'epreuve doit donc filtrer sur (session, matiere, niveau), jamais sur
(session, matiere) seul -- sinon .fetchone() retourne arbitrairement
l'une des deux et l'autre est silencieusement ignoree.

Necessite : pip install -U google-genai pydantic
Necessite : au moins une cle listee dans gemini_client.CLES_API_ENV

Usage :
    python tagger_exercices_bac_gemini.py                                    # Maths terminale, toutes les epreuves non taguees
    python tagger_exercices_bac_gemini.py --matiere Physique                  # Physique, tous niveaux, toutes les epreuves non taguees
    python tagger_exercices_bac_gemini.py --matiere Physique --niveau premiere --session 2024 --forcer  # une seule, pour test/relecture
"""

import sqlite3
import argparse
import time
from pathlib import Path
from typing import Optional

# Charge .env explicitement -- necessaire pour l'usage CLI direct
# (python tagger_exercices_bac_gemini.py), car rien d'autre ne charge
# ce fichier dans ce cas. Flask charge son propre .env au demarrage de
# app.py, mais ce script n'est jamais lance via Flask -- meme
# situation et meme fix que chat_llm_client.py. python-dotenv ignore
# silencieusement l'appel si .env est absent (ex: sur Render, ou les
# variables viennent directement de l'environnement du service).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pydantic import BaseModel
from google.genai import types

if __package__:
    from .gemini_client import construire_clients, generer_avec_fallback, MODELE_PAR_DEFAUT
else:
    from gemini_client import construire_clients, generer_avec_fallback, MODELE_PAR_DEFAUT

DB_PATH = Path("data/rag_maths_bac_c/rag.db")

PAUSE_ENTRE_APPELS = 2  # respect du rate-limit Gemini entre deux epreuves


# ═══════════════════════════════════════════════════════
# SCHEMA DE SORTIE CONTRAINTE -- meme principe que schema_epreuve.py :
# le SDK garantit la structure, pas besoin de parser un texte libre.
# ═══════════════════════════════════════════════════════

class TagSection(BaseModel):
    section_identifiant: str
    lecon_identifiants: list[str]  # peut etre vide -- voir garde-fou 3
    justification: str


class ResultatTagageEpreuve(BaseModel):
    sections: list[TagSection]


def construire_liste_lecons_valides(conn, matiere: str, niveau: str, series: Optional[str]) -> tuple[str, set[str]]:
    """Retourne (texte formate pour le prompt, ensemble des identifiants
    valides pour la validation post-hoc), filtre sur matiere+niveau, et
    sur la serie si l'identifiant suit le format PHY_{niveau}_{serie}_..
    (segment 3). Si series est None ou si le format ne s'applique pas
    (ex: Maths qui n'a qu'une serie C), aucun filtre de serie n'est
    applique -- comportement inchange pour Maths."""
    rows = conn.execute(
        "SELECT identifiant, titre FROM lecons WHERE matiere=? AND niveau=? ORDER BY chapitre_numero, lecon_numero",
        (matiere, niveau)
    ).fetchall()

    if series:
        rows_filtres = []
        for identifiant, titre in rows:
            segments = identifiant.split("_")
            # Format attendu : PREFIXE_NIVEAU_SERIE_CHAP_LECON (5 segments).
            # Si l'identifiant ne suit pas ce format (ex: ancien format
            # Maths "C01-L01"), on le garde tel quel sans filtrer --
            # evite de casser silencieusement Maths si son format differe.
            if len(segments) >= 3 and segments[2] == series:
                rows_filtres.append((identifiant, titre))
            elif len(segments) < 3:
                rows_filtres.append((identifiant, titre))
        rows = rows_filtres

    identifiants_valides = {r[0] for r in rows}
    texte = "\n".join(f"  {identifiant} — {titre}" for identifiant, titre in rows)
    return texte, identifiants_valides


def construire_prompt(liste_lecons_texte: str, sections: list[dict], matiere: str) -> str:
    sections_texte = "\n\n".join(
        f"--- SECTION \"{s['identifiant']}\" ({s['titre'] or s['type']}) ---\n{s['contenu_integral'][:2000]}"
        for s in sections
    )

    return f"""Tu es un professeur de {matiere.lower()} camerounais, expert du programme officiel \
(MINESEC, approche APC).

TÂCHE : pour CHAQUE section d'exercice ci-dessous, identifie la ou les leçons OFFICIELLES \
auxquelles son contenu appartient réellement -- UNIQUEMENT parmi la liste fermée fournie.

RÈGLES STRICTES, NON NÉGOCIABLES :
1. N'utilise QUE les identifiants de la liste ci-dessous, recopiés EXACTEMENT caractère pour \
   caractère. N'invente JAMAIS un identifiant, même s'il te semble plausible ou suit le même \
   format -- ne reconstruis jamais un identifiant de mémoire.
2. Une section porte AU MAXIMUM 2 leçons. Si plusieurs semblent pertinentes, choisis les 2 \
   les plus centrales au contenu réel, pas les plus générales.
3. NE TAGUE JAMAIS une leçon "par prudence" ou "par défaut" si le lien n'est pas clair et \
   direct. Si aucune leçon de la liste ne correspond clairement, retourne une liste VIDE pour \
   cette section -- une liste vide est un résultat correct et attendu, pas un échec.
4. Justifie CHAQUE leçon choisie en UNE phrase courte citant l'élément précis \
   (terme, notation, méthode, type de raisonnement) qui justifie ce choix -- jamais une \
   justification vague comme "cela concerne le programme".
5. Juge CHAQUE section indépendamment de son propre contenu -- ne recycle pas le thème d'une \
   section précédente par habitude.
6. Retourne EXACTEMENT une entrée par section fournie ci-dessous, ni plus ni moins, dans le \
   MÊME ORDRE -- ne subdivise jamais une section en plusieurs entrées et n'en fusionne jamais \
   deux, même si son contenu semble couvrir plusieurs sujets distincts.

LISTE FERMÉE DES LEÇONS VALIDES (identifiant — titre) :
{liste_lecons_texte}

SECTIONS À CLASSER :
{sections_texte}

Retourne un objet JSON strictement conforme au schéma fourni, une entrée par section, dans le \
même ordre que les sections ci-dessus."""


def valider_et_filtrer(resultat: ResultatTagageEpreuve, identifiants_valides: set[str]) -> list[TagSection]:
    """Garde-fou post-hoc (voir note en tete de fichier) -- rejette
    silencieusement (avec log) tout identifiant hallucine qui
    n'existerait pas reellement dans 'lecons' pour cette
    matiere/niveau/serie, meme si le schema Pydantic a ete respecte
    structurellement."""
    sections_validees = []
    for section in resultat.sections:
        lecons_filtrees = []
        for identifiant in section.lecon_identifiants:
            if identifiant in identifiants_valides:
                lecons_filtrees.append(identifiant)
            else:
                print(f"    ⚠️  Identifiant halluciné rejeté : {identifiant!r} "
                      f"(section {section.section_identifiant})")
        sections_validees.append(TagSection(
            section_identifiant=section.section_identifiant,
            lecon_identifiants=lecons_filtrees,
            justification=section.justification,
        ))
    return sections_validees


def creer_table_tags_si_absente(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tags_exercices_bac (
            section_id INTEGER NOT NULL REFERENCES sections_bac_officielles(id),
            lecon_identifiant TEXT NOT NULL REFERENCES lecons(identifiant),
            justification TEXT,
            PRIMARY KEY (section_id, lecon_identifiant)
        )
    """)


def obtenir_epreuves_a_traiter(conn, matiere: str, session_filtre: Optional[int], niveau_filtre: Optional[str], forcer: bool) -> list[tuple[int, str]]:
    """Retourne une liste de (session, niveau) -- pas juste session --
    car deux niveaux differents peuvent partager la meme annee (voir
    note en tete de fichier sur la collision session+matiere)."""
    query = "SELECT DISTINCT e.session, e.niveau FROM epreuves_bac_officielles e WHERE e.matiere=?"
    params = [matiere]
    if not forcer:
        query += """
            AND e.id NOT IN (
                SELECT DISTINCT s.epreuve_id FROM sections_bac_officielles s
                JOIN tags_exercices_bac t ON t.section_id = s.id
            )
        """
    if session_filtre:
        query += " AND e.session = ?"
        params.append(session_filtre)
    if niveau_filtre:
        query += " AND e.niveau = ?"
        params.append(niveau_filtre)
    query += " ORDER BY e.niveau, e.session"
    return [(row[0], row[1]) for row in conn.execute(query, params).fetchall()]


def tagger_epreuve(conn, clients, session: int, niveau: str, matiere: str) -> tuple[int, int]:
    """Tague une epreuve precise. La liste de lecons valides est
    construite ICI (pas dans main()) car elle depend de la serie de
    l'epreuve, qui varie d'une epreuve a l'autre au sein d'une meme
    matiere/niveau."""
    epreuve = conn.execute(
        "SELECT id, series FROM epreuves_bac_officielles WHERE session=? AND matiere=? AND niveau=?",
        (session, matiere, niveau)
    ).fetchone()
    if not epreuve:
        return 0, 0
    epreuve_id, series = epreuve

    liste_lecons_texte, identifiants_valides = construire_liste_lecons_valides(conn, matiere, niveau, series)
    if not identifiants_valides:
        print(f"    ⚠️  Aucune leçon trouvée pour {matiere}/{niveau}/{series}.")
        return 0, 0

    sections = conn.execute(
        "SELECT id, identifiant, type, titre, contenu_integral FROM sections_bac_officielles WHERE epreuve_id=? ORDER BY ordre",
        (epreuve_id,)
    ).fetchall()
    if not sections:
        return 0, 0

    sections_dicts = [
        {"id": s[0], "identifiant": s[1] or f"section_{i}", "type": s[2], "titre": s[3], "contenu_integral": s[4]}
        for i, s in enumerate(sections)
    ]
    # Matching par POSITION, pas par nom -- voir garde-fou 5 en tete
    # de fichier.
    id_reel_par_position = [sd["id"] for sd in sections_dicts]

    prompt = construire_prompt(liste_lecons_texte, sections_dicts, matiere)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ResultatTagageEpreuve,
        max_output_tokens=4000,
    )

    response, _, _ = generer_avec_fallback(clients, prompt, config)
    resultat = response.parsed if response.parsed else ResultatTagageEpreuve.model_validate_json(response.text)

    sections_validees = valider_et_filtrer(resultat, identifiants_valides)

    conn.execute("DELETE FROM tags_exercices_bac WHERE section_id IN (SELECT id FROM sections_bac_officielles WHERE epreuve_id=?)", (epreuve_id,))

    n_tags = 0
    if len(sections_validees) != len(id_reel_par_position):
        print(f"    ⚠️  Nombre de sections retournées ({len(sections_validees)}) différent du nombre attendu "
              f"({len(id_reel_par_position)}) -- matching positionnel impossible, tags ignorés pour cette épreuve.")
        conn.commit()
        return len(sections_dicts), 0

    for section_id, section_taguee in zip(id_reel_par_position, sections_validees):
        for lecon_id in section_taguee.lecon_identifiants:
            conn.execute(
                "INSERT OR REPLACE INTO tags_exercices_bac (section_id, lecon_identifiant, justification) VALUES (?, ?, ?)",
                (section_id, lecon_id, section_taguee.justification)
            )
            n_tags += 1

    conn.commit()
    return len(sections_dicts), n_tags


def main():
    parser = argparse.ArgumentParser(description="Tague les exercices réels du Bac sur les vraies leçons, via Gemini")
    parser.add_argument("--matiere", default="Mathematiques", help="Matiere a tagger")
    parser.add_argument("--niveau", default=None, help="Ne traiter qu'un niveau precis (terminale/premiere)")
    parser.add_argument("--session", type=int, default=None, help="Ne traiter qu'une session précise (test/relecture)")
    parser.add_argument("--forcer", action="store_true", help="Retague même les épreuves déjà traitées")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"❌ Base introuvable : {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    creer_table_tags_si_absente(conn)

    clients = construire_clients()
    epreuves = obtenir_epreuves_a_traiter(conn, args.matiere, args.session, args.niveau, args.forcer)

    if not epreuves:
        print("✅ Rien à faire -- toutes les épreuves sont déjà taguées (utilise --forcer pour retaguer).")
        conn.close()
        return

    print(f"🔧 Tagage de {len(epreuves)} épreuve(s) [{args.matiere}] : {epreuves}\n")

    total_sections = 0
    total_tags = 0
    for session, niveau in epreuves:
        print(f"  → {niveau} session {session}...")
        try:
            n_sections, n_tags = tagger_epreuve(conn, clients, session, niveau, args.matiere)
            print(f"    ✅ {n_sections} section(s), {n_tags} tag(s) posé(s)")
            total_sections += n_sections
            total_tags += n_tags
        except Exception as e:
            print(f"    ❌ Échec sur {niveau} session {session} : {e}")
        time.sleep(PAUSE_ENTRE_APPELS)

    conn.close()
    print(f"\n✅ Terminé -- {total_sections} section(s) traitée(s), {total_tags} tag(s) posé(s) au total.")


if __name__ == "__main__":
    main()