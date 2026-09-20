# scripts/retranscrire_lot_robuste.py
"""
Scanne data/pdfs_rag/<niveau>/<serie>/<matiere>/*.pdf, retranscrit
tout ce qui n'est pas déjà verifie_vision (ou qui l'est mais date
d'avant le correctif honnêteté tableaux/figures du 19/09/2026 --
détecté via colonne prompt_version), et journalise un résumé complet.

ROBUSTESSE : un fichier qui échoue (réseau, PDF corrompu, quota
Gemini) n'interrompt JAMAIS la boucle -- il est noté échoué et le
script continue sur le suivant. Peut être relancé autant de fois que
nécessaire : les épreuves déjà bien transcrites sont sautées, jamais
retranscrites deux fois (économie de coût Gemini).

USAGE :
    python scripts/retranscrire_lot_robuste.py --dry-run
    python scripts/retranscrire_lot_robuste.py
    python scripts/retranscrire_lot_robuste.py --forcer-tout
"""

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

from retranscrire_epreuve_vision import (
    transcrire_pdf, remplacer_sections, marquer_qualite_verifiee,
    afficher_resume_transcription, SegmentationIncomplete, DB_PATH,
)
from gemini_client import construire_clients

RACINE_PDFS = Path("data/pdfs_rag")

MOTIF_ANNEE = re.compile(r"(19[9]\d|20[0-3]\d)")

# Version du prompt actuellement en usage -- incrémenter ce numéro à
# chaque fois que PROMPT_TRANSCRIPTION change de façon significative,
# pour permettre de re-cibler uniquement les épreuves transcrites avec
# une version antérieure sans tout re-scanner à l'aveugle.
VERSION_PROMPT_ACTUELLE = "2026-09-19-honnetete-figures"

# Correspondance nom de dossier niveau -> valeur stockée en base
# (déjà la même convention que le reste du projet).
NIVEAUX_VALIDES = {"3e", "premiere", "terminale"}
# Les noms de dossiers ne correspondent pas toujours exactement au
# nom de matière stocké en base (casse, abréviation, variante
# orthographique historique) -- ce dict fait la traduction. Clé en
# minuscule pour un matching insensible à la casse du dossier.
NORMALISATION_MATIERE = {
    "maths": "Mathematiques",
    "mathematiques": "Mathematiques",
    "physique": "Physique",
    "informatique": "Informatique",
    "svteehb": "SVT",
    "svt": "SVT",
    "chimie": "Chimie",
}


def normaliser_matiere(nom_dossier: str) -> str:
    return NORMALISATION_MATIERE.get(nom_dossier.strip().lower(), nom_dossier)

def lister_pdfs():
    """Parcourt data/pdfs_rag/<niveau>/<serie>/<matiere>/*.pdf et
    retourne une liste de dicts {chemin, niveau, serie, matiere}.
    Ignore silencieusement toute arborescence qui ne respecte pas
    exactement 3 niveaux de dossiers sous la racine.

    CORRECTIF (19/09/2026) : le nom du dossier matière ne correspond
    pas toujours exactement au nom stocké en base (ex: dossier
    "maths" / "physique" / "SVTEEHB" vs colonne "Mathematiques" /
    "Physique" / "SVT") -- voir normaliser_matiere(). Sans ça, la
    recherche en base échouait silencieusement pour toutes ces
    matières malgré des lignes bien présentes."""
    resultats = []

    if not RACINE_PDFS.exists():
        print(f"❌ Dossier introuvable : {RACINE_PDFS}")
        return resultats

    for chemin_niveau in RACINE_PDFS.iterdir():
        if not chemin_niveau.is_dir():
            continue
        niveau = chemin_niveau.name
        if niveau not in NIVEAUX_VALIDES:
            print(f"⚠️  Dossier niveau ignoré (nom inattendu) : {chemin_niveau}")
            continue

        for chemin_serie in chemin_niveau.iterdir():
            if not chemin_serie.is_dir():
                continue
            serie = chemin_serie.name

            for chemin_matiere in chemin_serie.iterdir():
                if not chemin_matiere.is_dir():
                    continue
                matiere = chemin_matiere.name

                for pdf in chemin_matiere.glob("*.pdf"):
                    resultats.append({
                        "chemin": pdf,
                        "niveau": niveau,
                        "serie": serie,
                        "matiere": normaliser_matiere(matiere),
                    })

    return resultats


def extraire_annee(nom_fichier: str) -> int | None:
    match = MOTIF_ANNEE.search(nom_fichier)
    return int(match.group(1)) if match else None


def _colonne_existe(conn, table, colonne) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return colonne in {row[1] for row in cur.fetchall()}


def epreuve_deja_a_jour(conn, epreuve_id: str, forcer: bool) -> bool:
    """True si cette épreuve est déjà transcrite avec la version de
    prompt actuelle -- on ne la retranscrit pas (économie Gemini),
    sauf si --forcer-tout est passé."""
    if forcer:
        return False

    row = conn.execute(
        "SELECT qualite FROM epreuves_bac_officielles WHERE id=?",
        (epreuve_id,)
    ).fetchone()

    if not row or row[0] != "verifie_vision":
        return False

    if not _colonne_existe(conn, "epreuves_bac_officielles", "version_prompt"):
        # Colonne pas encore posée -- une épreuve verifie_vision sans
        # traçabilité de version est considérée comme transcrite AVANT
        # le correctif honnêteté, donc pas à jour.
        return False

    version_row = conn.execute(
        "SELECT version_prompt FROM epreuves_bac_officielles WHERE id=?",
        (epreuve_id,)
    ).fetchone()

    return version_row and version_row[0] == VERSION_PROMPT_ACTUELLE


def marquer_version_prompt(conn, epreuve_id: str):
    if not _colonne_existe(conn, "epreuves_bac_officielles", "version_prompt"):
        conn.execute(
            "ALTER TABLE epreuves_bac_officielles ADD COLUMN version_prompt TEXT"
        )
    conn.execute(
        "UPDATE epreuves_bac_officielles SET version_prompt=? WHERE id=?",
        (VERSION_PROMPT_ACTUELLE, epreuve_id)
    )


def trouver_epreuve_id(conn, niveau: str, serie: str, matiere: str, annee: int) -> str | None:
    row = conn.execute(
        "SELECT id FROM epreuves_bac_officielles WHERE niveau=? AND series=? AND matiere=? AND session=?",
        (niveau, serie, matiere, annee)
    ).fetchone()
    return row[0] if row else None


def traiter_un_pdf(clients, conn, item: dict, forcer: bool, dry_run: bool) -> str:
    """Retourne 'ok', 'saute', ou 'echec'."""
    chemin = item["chemin"]
    niveau, serie, matiere = item["niveau"], item["serie"], item["matiere"]

    annee = extraire_annee(chemin.name)
    if annee is None:
        print(f"⚠️  Année introuvable dans le nom -- ignoré : {chemin.name}")
        return "echec"

    epreuve_id = trouver_epreuve_id(conn, niveau, serie, matiere, annee)
    if epreuve_id is None:
        print(f"⚠️  Aucune ligne en base pour {niveau}/{serie}/{matiere}/{annee} -- "
              f"lancez d'abord preparer_import_generique.py --executer. Ignoré : {chemin.name}")
        return "echec"

    if epreuve_deja_a_jour(conn, epreuve_id, forcer):
        print(f"⏭️  Déjà à jour ({VERSION_PROMPT_ACTUELLE}) : {matiere} {niveau} {serie} {annee}")
        return "saute"

    print(f"\n🔍 {matiere} {niveau} {serie} {annee} -- {chemin.name}")

    try:
        transcription = transcrire_pdf(clients, chemin)
    except SegmentationIncomplete as exc:
        print(f"   ⚠️ Segmentation incomplète après plusieurs tentatives -- ignoré : {exc}")
        return "echec"
    except Exception as exc:
        print(f"   ❌ Échec transcription (réseau/quota/PDF) : {exc}")
        return "echec"

    afficher_resume_transcription(transcription)

    if dry_run:
        print("   🧪 dry-run -- aucune écriture en base.")
        return "ok"

    try:
        remplacer_sections(conn, epreuve_id, transcription)
        marquer_qualite_verifiee(conn, epreuve_id)
        marquer_version_prompt(conn, epreuve_id)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"   ❌ Échec écriture en base -- ignoré : {exc}")
        return "echec"

    print(f"   ✅ Terminé.")
    return "ok"


def main():
    parser = argparse.ArgumentParser(
        description="Retranscrit en boucle robuste tous les PDFs de data/pdfs_rag/, "
                    "en sautant ce qui est déjà à jour."
    )
    parser.add_argument("--dry-run", action="store_true",
                         help="Transcrit et affiche, mais n'écrit rien en base.")
    parser.add_argument("--forcer-tout", action="store_true",
                         help="Retranscrit même les épreuves déjà à jour -- coût Gemini réel, à utiliser avec discernement.")
    parser.add_argument("--pause-sec", type=float, default=1.5,
                         help="Pause entre deux appels Gemini pour ménager le quota (défaut: 1.5s).")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"❌ Base introuvable : {DB_PATH}")
        sys.exit(1)

    pdfs = lister_pdfs()
    if not pdfs:
        print("❌ Aucun PDF trouvé sous data/pdfs_rag/.")
        sys.exit(1)

    print(f"📂 {len(pdfs)} PDF(s) trouvé(s) sous {RACINE_PDFS}.\n")

    clients = construire_clients()
    conn = sqlite3.connect(DB_PATH)

    compteurs = {"ok": 0, "saute": 0, "echec": 0}
    echecs_detail = []

    for i, item in enumerate(pdfs, start=1):
        print(f"========== [{i}/{len(pdfs)}] ==========")
        try:
            resultat = traiter_un_pdf(clients, conn, item, args.forcer_tout, args.dry_run)
        except Exception as exc:
            # Filet de sécurité absolu -- même une erreur totalement
            # inattendue (bug dans le script lui-même) ne doit jamais
            # arrêter la boucle sur les fichiers restants.
            print(f"   ❌ Erreur inattendue, fichier ignoré : {exc}")
            resultat = "echec"

        compteurs[resultat] += 1
        if resultat == "echec":
            echecs_detail.append(str(item["chemin"]))

        if resultat == "ok" and not args.dry_run:
            time.sleep(args.pause_sec)

    conn.close()

    print("\n===================== RÉSUMÉ =====================")
    print(f"Réussis      : {compteurs['ok']}/{len(pdfs)}")
    print(f"Déjà à jour  : {compteurs['saute']}/{len(pdfs)}")
    print(f"Échoués      : {compteurs['echec']}/{len(pdfs)}")

    if echecs_detail:
        print("\nFichiers en échec (à examiner manuellement) :")
        for f in echecs_detail:
            print(f"  - {f}")


if __name__ == "__main__":
    main()