# scripts/retranscrire_epreuve_vision.py
"""
Re-transcription FIDÈLE d'une épreuve officielle à partir du PDF
original, via Gemini Vision.

CORRECTIF (29/08/2026) : `type` (champ libre du schéma Pydantic, non
contraint par une énumération) est normalisé en minuscule à
l'écriture -- voir remplacer_sections(). Sans cette normalisation,
Gemini peut renvoyer "Exercice", "EXERCICE" ou "exercice" selon les
appels, et toute comparaison SQL exacte ailleurs dans le code (voir
chat_bac_officiel.obtenir_exercice_bac, `type='exercice'`) échoue
silencieusement selon la casse réellement stockée -- bug constaté en
production sur la session 2024 (Bac jugé "introuvable" par le chat
alors que la donnée existait bel et bien en base, retranscrite avec
succès juste avant).

CORRECTIF (session de consolidation 1999-2018) : ajout de l'argument
--epreuve-id. Certaines sessions (ex: 2014) ont DEUX lignes distinctes
dans epreuves_bac_officielles pour la même (session, matiere) -- sans
ce paramètre, la sélection `WHERE session=? AND matiere=?` retourne
une ligne arbitraire via .fetchone(), risquant d'écraser la mauvaise
épreuve. --epreuve-id permet de cibler explicitement l'une des deux
lignes par son identifiant exact (ex: BAC-2014-15 ou BAC-2014-16).
Si --epreuve-id n'est pas fourni, comportement inchangé (recherche par
session+matiere) -- rétro-compatible avec tous les appels existants.

CORRECTIF HONNÊTETÉ TRANSCRIPTION (19/09/2026) : jusqu'ici, le prompt
ne mentionnait ni les tableaux ni les figures/graphiques -- face à un
tableau de données, Gemini le résumait souvent en une phrase vague au
lieu de le retranscrire fidèlement ; face à une figure/graphique/
schéma, il l'ignorait ou improvisait une description non vérifiable,
SANS jamais le signaler. Deux ajouts :
  1. Le prompt demande explicitement un tableau Markdown pour les
     tableaux, et une description structurée [FIGURE : ...] pour les
     éléments visuels non reproductibles en texte.
  2. Nouveau champ `elements_non_transcrits` (SectionTranscrite) :
     Gemini y consigne EXPLICITEMENT ce qu'il n'a pas pu transcrire
     avec confiance (scan flou, valeurs illisibles) au lieu de
     l'ignorer silencieusement ou d'inventer. Écrit en base par
     remplacer_sections() ; affiché à l'élève par
     chat_bac_officiel.formuler_reponse_exercice_bac(), qui l'oriente
     vers "Parcourir les épreuves" pour consulter le PDF original
     déjà disponible ailleurs sur le site -- jamais un vrai blocage.

IMPORTANT -- PORTÉE DE CE CORRECTIF : il ne s'applique qu'aux
transcriptions lancées APRÈS ce changement. Les épreuves déjà en base
(transcrites avant le 19/09/2026) n'ont pas ce traitement -- leurs
tableaux/figures éventuels restent tels quels tant qu'elles ne sont
pas retranscrites avec ce nouveau prompt.
"""

import sqlite3
import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from google.genai import types

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if __package__:
    from .gemini_client import construire_clients, generer_avec_fallback
else:
    from gemini_client import construire_clients, generer_avec_fallback


DB_PATH = Path("data/rag_maths_bac_c/rag.db")
DOSSIER_PREVISUALISATIONS = Path("previsualisations_transcription")

NB_TENTATIVES_TRANSCRIPTION = 3


class SectionTranscrite(BaseModel):
    identifiant: Optional[str] = None
    type: str
    titre: Optional[str] = None
    bareme_annonce: Optional[str] = None
    contenu_integral: str
    # NOUVEAU (19/09/2026) -- voir docstring en tête de fichier.
    # None si tout (texte, tableaux, figures) a été transcrit avec
    # confiance. Sinon, description courte et honnête de ce qui n'a
    # pas pu être transcrit fidèlement pour cette section.
    elements_non_transcrits: Optional[str] = None


class EpreuveTranscrite(BaseModel):
    sections: list[SectionTranscrite]


class SegmentationIncomplete(RuntimeError):
    def __init__(self, message: str, transcription: "EpreuveTranscrite"):
        super().__init__(message)
        self.transcription = transcription


PROMPT_TRANSCRIPTION = r"""
Tu es un transcripteur RIGOUREUX de documents scolaires camerounais.
Tu reçois le PDF SCANNÉ D'UNE ÉPREUVE OFFICIELLE.
Ta seule tâche est de TRANSCRIRE FIDÈLEMENT ce qui est réellement visible dans le PDF.

Tu ne dois PAS : résoudre, expliquer, corriger, compléter, inventer, résumer, ou supprimer.

RÈGLE ABSOLUE : une PARTIE et un EXERCICE sont des sections DISTINCTES.
Si le document contient PARTIE A / EXERCICE 1 / EXERCICE 2 / EXERCICE 3 / EXERCICE 4 / PARTIE B,
tu DOIS retourner exactement ces six sections, dans cet ordre. Ne fusionne JAMAIS des exercices
dans le contenu_integral d'une partie.

FIDÉLITÉ : transcris exactement les valeurs, coefficients, signes, numérotation, barèmes.
Toute notation mathématique en LaTeX entre $...$. Si illisible, écris "[illisible]" -- ne
devine jamais. Ignore uniquement les artefacts de scan (CamScanner, numéros de page).

TABLEAUX : si l'énoncé contient un tableau de données (valeurs numériques, tableau de
correspondance, grille de résultats), retranscris-le comme un vrai tableau au format Markdown
(colonnes séparées par |, ligne d'en-tête suivie d'une ligne de séparation ---). Ne le
remplace JAMAIS par une simple liste ou une phrase qui en résume le contenu -- l'élève doit
pouvoir lire les mêmes valeurs, dans la même disposition, que sur le document original.

FIGURES, GRAPHIQUES ET SCHÉMAS (courbes, figures géométriques, diagrammes, schémas de
circuit électrique, dispositifs expérimentaux) : tu ne peux PAS reproduire une image. À
la place, décris-la de façon PRÉCISE et STRUCTURÉE juste après la mention de sa présence
dans le texte, sous la forme :
[FIGURE : description] suivi des éléments réellement visibles et utiles à la résolution
(nature de la figure, axes et leurs unités si un graphique, points remarquables et leurs
coordonnées ou noms si indiqués sur le schéma, valeurs numériques inscrites sur la figure,
formes ou objets représentés). Ne décris QUE ce qui est explicitement visible ou étiqueté
sur le document -- ne déduis et n'invente aucune valeur qui ne serait pas lisible.

HONNÊTETÉ OBLIGATOIRE SUR CE QUE TU N'AS PAS PU TRANSCRIRE :
Pour chaque section, si tu rencontres un élément (figure, graphique, schéma, tableau,
diagramme, ou même un passage de texte) que tu n'es PAS en mesure de transcrire avec
confiance -- parce que le scan est trop flou, trop petit, coupé, ou que des valeurs
essentielles ne sont pas clairement lisibles -- tu DOIS le signaler dans le champ
`elements_non_transcrits` de cette section, avec une description courte et honnête du
problème (ex: "Figure présente en haut de l'exercice 2 : graphique dont les graduations des
axes sont illisibles sur le scan" ou "Tableau visible mais deux cellules sont masquées par
une tache d'encre"). Ne force JAMAIS une description complète et assurée d'un élément que tu
ne peux pas réellement lire -- un aveu clair et localisé vaut mieux qu'une description
inventée qui semblerait fiable. Si tout le contenu de la section a pu être transcrit avec
confiance (texte, tableaux et figures compris), laisse `elements_non_transcrits` à null --
ne le remplis jamais par prudence excessive sur du contenu que tu as réellement bien vu.

Retourne uniquement un objet JSON strictement conforme au schéma fourni.
"""

PROMPT_REPARATION_SEGMENTATION = r"""
IMPORTANT : la réponse précédente a été jugée trop grossière au niveau de la segmentation.
Relis DIRECTEMENT le PDF. Chaque "PARTIE ..." et chaque "EXERCICE ..." visible doit être une
section indépendante. Ne fusionne jamais deux exercices. Retranscris TOUT le contenu, y compris
les sous-questions et barèmes. Ne résous rien, ne corrige rien, n'invente rien. LaTeX entre $...$.

Les mêmes règles s'appliquent que dans la consigne initiale : tableaux en Markdown, figures
décrites sous [FIGURE : ...], et tout élément non transcriptible avec confiance signalé
honnêtement dans `elements_non_transcrits` plutôt qu'ignoré ou inventé.

Retourne uniquement le JSON conforme au schéma.
"""


def _compter_exercices_dans_transcription(transcription: EpreuveTranscrite) -> int:
    texte = "\n".join(
        f"{section.identifiant or ''}\n{section.titre or ''}\n{section.contenu_integral}"
        for section in transcription.sections
    )
    matches = re.findall(r"\b(?:EXERCICE|Exercice|exercice)\s*([0-9]+)\b", texte)
    return len(set(matches))


def _sections_exercices(transcription: EpreuveTranscrite) -> list[SectionTranscrite]:
    resultat = []
    for section in transcription.sections:
        texte = " ".join(x for x in [section.identifiant, section.titre] if x)
        if re.search(r"\b(?:EXERCICE|Exercice|exercice)\s*[0-9]+\b", texte):
            resultat.append(section)
    return resultat


def _segmentation_manifestement_incomplete(transcription: EpreuveTranscrite) -> bool:
    nb_exercices_mentions = _compter_exercices_dans_transcription(transcription)
    nb_sections_exercices = len(_sections_exercices(transcription))
    if nb_exercices_mentions >= 2 and nb_sections_exercices == 0:
        return True
    if nb_exercices_mentions >= 3 and nb_sections_exercices < 2:
        return True
    return False


def transcrire_pdf(clients, chemin_pdf: Path) -> EpreuveTranscrite:
    pdf_bytes = chemin_pdf.read_bytes()
    prompts = [
        PROMPT_TRANSCRIPTION,
        PROMPT_TRANSCRIPTION + "\n\n" + PROMPT_REPARATION_SEGMENTATION,
        PROMPT_REPARATION_SEGMENTATION,
    ]

    derniere_transcription = None
    derniere_erreur = None

    for numero_tentative, prompt in enumerate(prompts[:NB_TENTATIVES_TRANSCRIPTION], start=1):
        print(f"   ↳ Tentative de transcription/segmentation {numero_tentative}/{NB_TENTATIVES_TRANSCRIPTION}...")

        contenu = types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                types.Part(text=prompt),
            ],
        )
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=EpreuveTranscrite,
            max_output_tokens=12000,
        )

        try:
            response, _, _ = generer_avec_fallback(clients, contenu, config)
            transcription = response.parsed if response.parsed else EpreuveTranscrite.model_validate_json(response.text)
            derniere_transcription = transcription

            nb_sections = len(transcription.sections)
            nb_exercices = len(_sections_exercices(transcription))
            print(f"      → {nb_sections} section(s), {nb_exercices} section(s) exercice(s)")

            if not _segmentation_manifestement_incomplete(transcription):
                return transcription

            if numero_tentative < NB_TENTATIVES_TRANSCRIPTION:
                print("      ⚠️ Segmentation trop grossière détectée. Nouvelle lecture avec consigne renforcée...")

        except Exception as exc:
            derniere_erreur = exc
            if numero_tentative < NB_TENTATIVES_TRANSCRIPTION:
                print(f"      ⚠️ Tentative échouée : {exc}\n      Nouvelle tentative...")
            else:
                raise

    if derniere_transcription is not None:
        raise SegmentationIncomplete(
            f"Gemini a produit une transcription, mais la segmentation reste manifestement "
            f"incomplète après {NB_TENTATIVES_TRANSCRIPTION} tentatives. Aucune écriture en "
            f"base n'a été effectuée.",
            transcription=derniere_transcription,
        ) from derniere_erreur

    raise RuntimeError("Impossible d'obtenir une transcription valide.") from derniere_erreur


def _colonne_elements_non_transcrits_existe(conn) -> bool:
    cur = conn.execute("PRAGMA table_info(sections_bac_officielles)")
    colonnes = {row[1] for row in cur.fetchall()}
    return "elements_non_transcrits" in colonnes


def remplacer_sections(conn, epreuve_id: str, transcription: EpreuveTranscrite) -> int:
    # NOUVEAU (19/09/2026) -- ajoute la colonne si elle n'existe pas
    # encore (base pas migrée), même logique défensive que
    # marquer_qualite_verifiee() pour la colonne `qualite`.
    if not _colonne_elements_non_transcrits_existe(conn):
        conn.execute(
            "ALTER TABLE sections_bac_officielles ADD COLUMN elements_non_transcrits TEXT"
        )

    anciennes_sections = conn.execute(
        "SELECT id FROM sections_bac_officielles WHERE epreuve_id=?", (epreuve_id,)
    ).fetchall()
    for (section_id,) in anciennes_sections:
        conn.execute("DELETE FROM questions_bac_officielles WHERE section_id=?", (section_id,))
        conn.execute("DELETE FROM tags_exercices_bac WHERE section_id=?", (section_id,))
    conn.execute("DELETE FROM sections_bac_officielles WHERE epreuve_id=?", (epreuve_id,))

    for ordre, section in enumerate(transcription.sections):
        conn.execute("""
            INSERT INTO sections_bac_officielles
            (epreuve_id, ordre, identifiant, type, titre, bareme_annonce, contenu_integral, elements_non_transcrits)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            epreuve_id, ordre, section.identifiant,
            (section.type or "").strip().lower(),  # CORRECTIF (29/08/2026) -- voir tête de fichier
            section.titre, section.bareme_annonce, section.contenu_integral,
            section.elements_non_transcrits,
        ))

    return len(transcription.sections)


def marquer_qualite_verifiee(conn, epreuve_id: str):
    cur = conn.execute("PRAGMA table_info(epreuves_bac_officielles)")
    colonnes = {row[1] for row in cur.fetchall()}
    if "qualite" not in colonnes:
        conn.execute("ALTER TABLE epreuves_bac_officielles ADD COLUMN qualite TEXT DEFAULT 'ocr_brut'")
    conn.execute("UPDATE epreuves_bac_officielles SET qualite='verifie_vision' WHERE id=?", (epreuve_id,))


def afficher_resume_transcription(transcription: EpreuveTranscrite):
    print("\n   Structure détectée :")
    for index, section in enumerate(transcription.sections, start=1):
        longueur = len(section.contenu_integral)
        print(f"   {index}. [{section.type}] {section.identifiant or '(sans identifiant)'} -- "
              f"{section.titre or '(sans titre)'} -- barème: {section.bareme_annonce or '?'} -- {longueur} caractères")
        if section.elements_non_transcrits:
            print(f"      ⚠️ Non transcrit avec confiance : {section.elements_non_transcrits}")


def _sauver_apercu(transcription: EpreuveTranscrite, matiere: str, session: int, incomplet: bool = False) -> Path:
    DOSSIER_PREVISUALISATIONS.mkdir(exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffixe = "_SEGMENTATION_INCOMPLETE" if incomplet else ""
    nom_sortie = f"apercu_{matiere}_{session}_{horodatage}{suffixe}.json"
    chemin_sortie = DOSSIER_PREVISUALISATIONS / nom_sortie
    chemin_sortie.write_text(json.dumps(transcription.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return chemin_sortie


def main():
    parser = argparse.ArgumentParser(description="Retranscrit fidèlement une épreuve officielle depuis son PDF source, via Gemini Vision.")
    parser.add_argument("--fichier", type=Path, required=True)
    parser.add_argument("--session", type=int, required=True)
    parser.add_argument("--matiere", default="Mathematiques")
    parser.add_argument("--series", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--epreuve-id", default=None,
                         help="Cible un id précis (ex: BAC-2014-16) au lieu de session+matiere -- "
                              "nécessaire quand plusieurs épreuves partagent la même session/série.")
    args = parser.parse_args()

    if not args.fichier.exists():
        print(f"❌ Fichier introuvable : {args.fichier}")
        return

    epreuve_id = None
    conn = None

    if not args.dry_run:
        if not DB_PATH.exists():
            print(f"❌ Base introuvable : {DB_PATH}")
            return
        conn = sqlite3.connect(DB_PATH)
        if args.epreuve_id:
            epreuve = conn.execute(
                "SELECT id FROM epreuves_bac_officielles WHERE id=?", (args.epreuve_id,)
            ).fetchone()
        else:
            epreuve = conn.execute(
                "SELECT id FROM epreuves_bac_officielles WHERE session=? AND matiere=?",
                (args.session, args.matiere)
            ).fetchone()
        if not epreuve:
            cible = args.epreuve_id or f"{args.matiere} session {args.session}"
            print(f"❌ Aucune épreuve trouvée pour : {cible}")
            conn.close()
            return
        epreuve_id = epreuve[0]
    else:
        if DB_PATH.exists():
            conn_verif = sqlite3.connect(DB_PATH)
            if args.epreuve_id:
                epreuve = conn_verif.execute(
                    "SELECT id FROM epreuves_bac_officielles WHERE id=?", (args.epreuve_id,)
                ).fetchone()
            else:
                epreuve = conn_verif.execute(
                    "SELECT id FROM epreuves_bac_officielles WHERE session=? AND matiere=?",
                    (args.session, args.matiere)
                ).fetchone()
            conn_verif.close()
            if epreuve:
                epreuve_id = epreuve[0]
        print("🧪 MODE DRY-RUN -- aucune écriture ne sera faite dans rag.db.\n")

    print(f"🔍 Transcription du PDF via Gemini Vision : {args.fichier.name}...")
    clients = construire_clients()

    try:
        transcription = transcrire_pdf(clients, args.fichier)
    except SegmentationIncomplete as exc:
        if args.dry_run:
            chemin_sortie = _sauver_apercu(exc.transcription, args.matiere, args.session, incomplet=True)
            print(f"\n⚠️ {exc}\n   Aperçu PARTIEL sauvé : {chemin_sortie}")
            afficher_resume_transcription(exc.transcription)
        else:
            print(f"❌ {exc}")
            if conn is not None:
                conn.close()
        return

    if args.dry_run:
        chemin_sortie = _sauver_apercu(transcription, args.matiere, args.session)
        print(f"\n✅ Prévisualisation générée -- {len(transcription.sections)} section(s).")
        print(f"   Fichier complet : {chemin_sortie}")
        afficher_resume_transcription(transcription)
        return

    try:
        n_sections = remplacer_sections(conn, epreuve_id, transcription)
        marquer_qualite_verifiee(conn, epreuve_id)
        if args.series:
            conn.execute("UPDATE epreuves_bac_officielles SET series=? WHERE id=?", (args.series, epreuve_id))
        conn.commit()
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()

    print(f"✅ Terminé -- {n_sections} section(s) retranscrite(s) pour {args.matiere} session {args.session}.")
    afficher_resume_transcription(transcription)


if __name__ == "__main__":
    main()