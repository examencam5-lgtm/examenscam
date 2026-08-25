# scripts/extraire_texte_pdfs.py
"""
ÉTAPE 2 du pipeline RAG Maths Terminale C.

Ouvre chaque PDF déjà téléchargé (chemin_pdf_local en base) et
extrait son texte brut avec pypdf. Met à jour texte_extrait et
statut_extraction pour chaque épreuve.

Volontairement séparé du scraping (étape 1) : si l'extraction plante
sur un PDF pourri ou scanné, on ne relance pas tout le téléchargement
-- on peut relancer CE script seul, autant de fois que nécessaire.

Statuts possibles après passage :
    - "ok"            : texte extrait, longueur suffisante
    - "vide_ou_scan"  : le PDF s'est ouvert mais quasi aucun texte
                        n'a été extrait -> probablement un PDF scanné
                        (image), nécessitera de l'OCR plus tard
    - "echec_lecture" : le fichier n'a pas pu être ouvert du tout
                        (corrompu, tronqué par une coupure réseau...)

Usage :
    python extraire_texte_pdfs.py                # traite tout ce qui
                                                   # est 'non_traite'
    python extraire_texte_pdfs.py --tout          # retraite même les
                                                   # épreuves déjà 'ok'
"""

import sqlite3
import argparse
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

DB_PATH = Path("data/rag_maths_bac_c/rag.db")

# En dessous de ce nombre de caractères, on considère que
# l'extraction a probablement échoué à cause d'un PDF scanné (image)
# plutôt qu'un vrai texte sélectionnable.
SEUIL_TEXTE_MINIMUM = 200


def nettoyer_texte_pour_sqlite(texte: str) -> str:
    """Certains PDFs mal encodés produisent des caractères Unicode
    invalides (surrogates isolés, ex: \\udf00) que SQLite/UTF-8 refuse
    de stocker. On les supprime proprement plutôt que de planter."""
    if texte is None:
        return texte
    return texte.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="ignore")


def extraire_texte_pdf(chemin: str):
    """Retourne (texte, statut). Ne lève jamais d'exception -- toute
    erreur est capturée et traduite en statut, pour ne jamais
    interrompre le traitement du lot entier à cause d'UN fichier."""
    chemin_path = Path(chemin)
    if not chemin_path.exists():
        return None, "fichier_introuvable"

    try:
        reader = PdfReader(str(chemin_path))
        texte_pages = []
        for page in reader.pages:
            texte_pages.append(page.extract_text() or "")
        texte = "\n".join(texte_pages).strip()
    except (PdfReadError, OSError, Exception) as e:
        return None, f"echec_lecture"

    if len(texte) < SEUIL_TEXTE_MINIMUM:
        return nettoyer_texte_pour_sqlite(texte), "vide_ou_scan"

    return nettoyer_texte_pour_sqlite(texte), "ok"


def main():
    parser = argparse.ArgumentParser(description="Extraction texte des PDFs — étape 2")
    parser.add_argument("--tout", action="store_true",
                         help="Retraite aussi les épreuves déjà marquées 'ok'")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"❌ Base introuvable : {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)

    if args.tout:
        cur = conn.execute("SELECT id, titre_original, chemin_pdf_local FROM epreuves")
    else:
        cur = conn.execute("""
            SELECT id, titre_original, chemin_pdf_local FROM epreuves
            WHERE statut_extraction != 'ok' OR statut_extraction IS NULL
        """)
    lignes = cur.fetchall()

    print(f"📄 {len(lignes)} épreuve(s) à traiter...\n")

    compteurs = {"ok": 0, "vide_ou_scan": 0, "echec_lecture": 0, "fichier_introuvable": 0}

    for id_, titre, chemin in lignes:
        texte, statut = extraire_texte_pdf(chemin)
        compteurs[statut] = compteurs.get(statut, 0) + 1

        symbole = {"ok": "✅", "vide_ou_scan": "🖼️ ", "echec_lecture": "❌",
                   "fichier_introuvable": "❓"}.get(statut, "?")
        nb_caracteres = len(texte) if texte else 0
        print(f"  {symbole} [ID {id_}] ({nb_caracteres} car.) {titre[:60]}")

        try:
            conn.execute("""
                UPDATE epreuves SET texte_extrait = ?, statut_extraction = ?
                WHERE id = ?
            """, (texte, statut, id_))
            conn.commit()  # commit à CHAQUE ligne -> reprenable en cas de crash
        except Exception as e:
            # Filet de sécurité : si une ligne pose un problème imprévu
            # (encodage, taille...), on ne perd pas tout le lot déjà
            # traité -- on note l'échec et on continue.
            print(f"    ⚠️ Échec d'enregistrement en base pour l'ID {id_} : {e}")
            conn.rollback()
            compteurs["echec_lecture"] = compteurs.get("echec_lecture", 0) + 1

    conn.close()

    print("\n" + "═" * 50)
    print("BILAN DE L'EXTRACTION")
    print("═" * 50)
    for statut, count in compteurs.items():
        print(f"  {statut:20s} : {count}")
    print("\nNote : les statuts 'vide_ou_scan' nécessiteront de l'OCR")
    print("       (pytesseract + pdf2image) pour être exploitables.")
    print("       Les 'fichier_introuvable' viennent probablement des")
    print("       échecs réseau du scraping -> à re-télécharger.")


if __name__ == "__main__":
    main()