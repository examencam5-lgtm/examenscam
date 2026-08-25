# scripts/scrape_rag_maths_tc.py
"""
Scraper DÉDIÉ au projet RAG — Maths Terminale C uniquement.

Contrairement à scrape_sujetexa.py (qui indexe des liens pour le site
principal), ce script :
  1. Télécharge RÉELLEMENT les PDFs sur disque (pas juste les liens)
  2. Extrait des métadonnées enrichies depuis le titre (séquence,
     type de document, établissement)
  3. Stocke tout directement dans une base SQLite dédiée au RAG

Ce script ne fait QUE le catalogage + téléchargement. Il ne touche
pas au contenu des PDFs (pas d'extraction de texte ici — c'est
l'étape 2, volontairement séparée : si l'extraction texte plante sur
un PDF pourri, on ne relance pas tout le scraping).

Usage :
    python scrape_rag_maths_tc.py                 # scrape toutes les pages
    python scrape_rag_maths_tc.py --max-pages 2    # limite pour un test

Sortie :
    - data/rag_maths_bac_c/pdfs/{id}.pdf   (les fichiers téléchargés)
    - data/rag_maths_bac_c/rag.db          (base SQLite, table epreuves)
"""

import re
import sys
import time
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════
# CONFIGURATION — restreinte à Maths Terminale C uniquement
# ═══════════════════════════════════════════════════════

SLUG_MATHS_TC = "terminale-c/maths_tc"
BASE_URL = "https://sujetexa.com/index.php/category"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RAGMathsTC/1.0)"}

MAX_TENTATIVES = 3
PAUSE_ENTRE_TENTATIVES = 5
PAUSE_ENTRE_REQUETES = 1       # respect du serveur source
PAUSE_ENTRE_TELECHARGEMENTS = 1.5

DATA_DIR = Path("data/rag_maths_bac_c")
PDF_DIR = DATA_DIR / "pdfs"
DB_PATH = DATA_DIR / "rag.db"


# ═══════════════════════════════════════════════════════
# RÉSEAU — même logique de retry que le scraper existant
# ═══════════════════════════════════════════════════════

def requete_avec_retry(url, description=""):
    """GET avec jusqu'à MAX_TENTATIVES essais en cas d'erreur réseau.
    Retourne la Response si succès, None si les tentatives échouent
    (l'appelant doit gérer ce cas sans planter tout le script)."""
    for tentative in range(1, MAX_TENTATIVES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            return resp
        except requests.exceptions.ConnectionError as e:
            print(f"  ⚠️ Tentative {tentative}/{MAX_TENTATIVES} échouée ({description or url}) : {e}")
            if tentative < MAX_TENTATIVES:
                time.sleep(PAUSE_ENTRE_TENTATIVES)
        except requests.exceptions.Timeout:
            print(f"  ⚠️ Timeout tentative {tentative}/{MAX_TENTATIVES} ({description or url})")
            if tentative < MAX_TENTATIVES:
                time.sleep(PAUSE_ENTRE_TENTATIVES)
    print(f"  ❌ Abandon après {MAX_TENTATIVES} tentatives : {description or url}")
    return None


# ═══════════════════════════════════════════════════════
# EXTRACTION DE MÉTADONNÉES DEPUIS LE TITRE
# ═══════════════════════════════════════════════════════

def extraire_annee(titre: str):
    matches = re.findall(r'(19[9]\d|20[0-2]\d)', titre)
    return int(matches[-1]) if matches else None


def extraire_sequence(titre: str):
    """Cherche 'SEQUENCE 3', 'SÉQUENCE 3', 'SEQ 3', 'SEQ3', ou en toutes
    lettres 'TROISIEME SEQUENCE'. Insensible aux accents/casse.
    Retourne un entier 1-6, ou None si absent."""
    titre_norm = titre.upper().replace("É", "E").replace("È", "E")

    match = re.search(r'S[EÉ]QUENCE\s*N?°?\s*(\d)', titre_norm)
    if match:
        return int(match.group(1))

    match = re.search(r'\bSEQ\.?\s*N?°?\s*(\d)\b', titre_norm)
    if match:
        return int(match.group(1))

    # Nombres écrits en toutes lettres, ex: "TROISIEME SEQUENCE"
    ordinaux = {
        "PREMIERE": 1, "1ERE": 1, "1ER": 1,
        "DEUXIEME": 2, "2EME": 2,
        "TROISIEME": 3, "3EME": 3,
        "QUATRIEME": 4, "4EME": 4,
        "CINQUIEME": 5, "5EME": 5,
        "SIXIEME": 6, "6EME": 6,
    }
    for mot, num in ordinaux.items():
        if re.search(rf'{mot}\s+S[EÉ]QUENCE', titre_norm) or re.search(rf'S[EÉ]QUENCE\s+{mot}', titre_norm):
            return num

    return None


def detecter_type_document(titre: str) -> str:
    """Classe le document par mots-clés. Important pour pouvoir exclure
    plus tard les TD/olympiades du corpus de génération."""
    t = titre.upper()
    if "OLYMPIADE" in t:
        return "olympiade"
    if "DEVOIR HARMONIS" in t:
        return "devoir_harmonise"
    if "TRAVAUX DIRIG" in t or re.search(r'\bTD\b', t):
        return "td"
    if "SEQUENCE" in t or "SÉQUENCE" in t or re.search(r'\bSEQ\b', t):
        return "sequence"
    if "CONTROLE" in t or "ÉVALUATION" in t or "EVALUATION" in t:
        return "evaluation_diverse"
    return "autre"


def extraire_etablissement(titre: str, type_document: str):
    """Le titre suit généralement le motif :
       MATIERE-ETABLISSEMENT-INFOS COMPLEMENTAIRES-...
    On prend le 2e segment séparé par des tirets, en le nettoyant.

    Cette heuristique ne marche que sur les titres 'standards'
    (type_document == sequence / devoir_harmonise / evaluation_diverse).
    Pour les TD, olympiades et autres formats libres, le 2e segment
    n'est pas fiable -> on retourne None plutôt qu'une valeur fausse.

    Filtres de rejet (candidat clairement PAS un établissement) :
    - commence par un chiffre (date, année scolaire)
    - contient "NIVEAU", "CONTROLE", "EPREUVE", "EVALUATION", "TRIMESTRE"
      (ce sont des mots de métadonnées, pas des noms d'établissement)
    - trop court (1-2 caractères, signe d'un split cassé sur "F-X. VOGT"
      ou "COLLÈGE F" par exemple)
    """
    if type_document not in ("sequence", "devoir_harmonise", "evaluation_diverse"):
        return None

    segments = [s.strip() for s in titre.split("-") if s.strip()]
    if len(segments) < 2:
        return None

    candidat = segments[1]

    mots_rejet = ("NIVEAU", "CONTROLE", "EPREUVE", "EVALUATION", "TRIMESTRE")
    if re.match(r'^\d', candidat):
        return None
    if any(candidat.upper().startswith(m) for m in mots_rejet):
        return None
    if len(candidat) <= 3:
        # Probablement un split cassé (ex: candidat == "F" issu de
        # "COLLÈGE F-X. VOGT") -> on recolle avec le segment suivant
        if len(segments) >= 3:
            candidat = f"{candidat}-{segments[2]}"
        else:
            return None

    # Cas "COLLÈGE F-X. VOGT" : le split coupe après "F" qui reste
    # collé au nom -> le DERNIER mot du candidat est une simple
    # initiale (1-2 lettres) -> signe d'un nom coupé, on recolle aussi.
    dernier_mot = candidat.split()[-1] if candidat.split() else ""
    if len(dernier_mot) <= 2 and len(segments) >= 3:
        candidat = f"{candidat}-{segments[2]}"

    return candidat


def detecter_matiere_suspecte(titre: str) -> bool:
    """Le slug 'maths_tc' est parfois pollué par d'autres matières
    mal classées côté source (vu dans les données réelles : de
    l'Informatique catalogué comme Maths). On vérifie que le titre
    ne commence pas explicitement par une autre matière connue."""
    autres_matieres = (
        "INFORMATIQUE", "PHYSIQUE", "CHIMIE", "SVT", "FRANCAIS",
        "FRANÇAIS", "ANGLAIS", "PHILOSOPHIE", "HISTOIRE", "GEOGRAPHIE",
        "GÉOGRAPHIE", "LITTERATURE", "LITTÉRATURE",
    )
    titre_upper = titre.upper().strip()
    return any(titre_upper.startswith(m) for m in autres_matieres)


def extraire_serie_cible(titre: str) -> str:
    """Certaines épreuves 'Maths TC' sont en fait mutualisées avec
    d'autres séries (TLeCD, TLeACD...). On le détecte pour garder une
    trace, sans exclure ces épreuves (Maths y est identique)."""
    t = titre.upper().replace(" ", "")
    match = re.search(r'TLE?([ACDEI,/]{1,6})', t)
    if match:
        lettres = match.group(1).replace("/", ",").strip(",")
        return lettres
    return "C"


# ═══════════════════════════════════════════════════════
# BASE DE DONNÉES
# ═══════════════════════════════════════════════════════

def initialiser_base():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS epreuves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titre_original TEXT NOT NULL,
            annee INTEGER,
            sequence INTEGER,
            type_document TEXT,
            etablissement TEXT,
            serie_cible TEXT,
            matiere_suspecte INTEGER DEFAULT 0,
            lien_pdf TEXT UNIQUE,
            lien_page TEXT,
            chemin_pdf_local TEXT,
            texte_extrait TEXT,
            statut_extraction TEXT DEFAULT 'non_traite',
            bareme_total REAL,
            date_scraping TEXT
        )
    """)
    conn.commit()
    return conn


def epreuve_deja_en_base(conn, lien_pdf: str) -> bool:
    cur = conn.execute("SELECT 1 FROM epreuves WHERE lien_pdf = ?", (lien_pdf,))
    return cur.fetchone() is not None


def inserer_epreuve(conn, metadonnees: dict):
    conn.execute("""
        INSERT INTO epreuves (
            titre_original, annee, sequence, type_document, etablissement,
            serie_cible, matiere_suspecte, lien_pdf, lien_page, chemin_pdf_local,
            statut_extraction, date_scraping
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'non_traite', ?)
    """, (
        metadonnees["titre"], metadonnees["annee"], metadonnees["sequence"],
        metadonnees["type_document"], metadonnees["etablissement"],
        metadonnees["serie_cible"], metadonnees["matiere_suspecte"],
        metadonnees["lien_pdf"], metadonnees["lien_page"],
        metadonnees["chemin_pdf_local"],
        datetime.now().isoformat(timespec="seconds"),
    ))
    conn.commit()


# ═══════════════════════════════════════════════════════
# TÉLÉCHARGEMENT PDF
# ═══════════════════════════════════════════════════════

def telecharger_pdf(lien_pdf: str, chemin_local: Path) -> bool:
    """Télécharge le PDF sur disque. Retourne True si succès."""
    resp = requete_avec_retry(lien_pdf, "téléchargement PDF")
    if resp is None or resp.status_code != 200:
        return False
    try:
        chemin_local.write_bytes(resp.content)
        return True
    except OSError as e:
        print(f"  ❌ Écriture disque échouée pour {chemin_local} : {e}")
        return False


# ═══════════════════════════════════════════════════════
# EXTRACTION DU LIEN PDF DEPUIS LA PAGE ARTICLE
# ═══════════════════════════════════════════════════════

def extraire_lien_pdf_article(page_url: str) -> str:
    resp = requete_avec_retry(page_url, "page article")
    if resp is None or resp.status_code != 200:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        if a["href"].lower().endswith(".pdf"):
            return a["href"]
    return ""


# ═══════════════════════════════════════════════════════
# BOUCLE PRINCIPALE DE SCRAPING
# ═══════════════════════════════════════════════════════

def scraper_et_telecharger(max_pages: int, limite_test: int = None):
    conn = initialiser_base()

    total_trouvees = 0
    total_telechargees = 0
    total_deja_en_base = 0
    total_echecs = 0

    page = 1
    echecs_consecutifs = 0

    while page <= max_pages:
        url = f"{BASE_URL}/{SLUG_MATHS_TC}/" if page == 1 else f"{BASE_URL}/{SLUG_MATHS_TC}/page/{page}/"
        print(f"\n📄 Page {page} : {url}")

        resp = requete_avec_retry(url, f"page {page}")
        if resp is None:
            echecs_consecutifs += 1
            if echecs_consecutifs >= 2:
                print("  ❌ Deux échecs consécutifs, arrêt du scraping.")
                break
            page += 1
            continue
        echecs_consecutifs = 0

        if resp.status_code == 404:
            print("  Fin de pagination (404).")
            break
        if resp.status_code != 200:
            print(f"  ⚠️ Statut {resp.status_code}, arrêt.")
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = soup.find_all("h2")
        if not articles:
            print("  Aucun article trouvé, fin de pagination.")
            break

        for h2 in articles:
            lien_titre = h2.find("a")
            if not lien_titre:
                continue

            titre = lien_titre.get_text(strip=True)
            lien_page = lien_titre.get("href", "")
            total_trouvees += 1

            print(f"\n  → {titre[:80]}...")

            lien_pdf = extraire_lien_pdf_article(lien_page)
            if not lien_pdf:
                print("    ⚠️ Pas de PDF trouvé sur la page, ignoré.")
                total_echecs += 1
                time.sleep(PAUSE_ENTRE_REQUETES)
                continue

            if epreuve_deja_en_base(conn, lien_pdf):
                print("    ↷ Déjà en base, ignoré.")
                total_deja_en_base += 1
                continue

            annee = extraire_annee(titre)
            sequence = extraire_sequence(titre)
            type_doc = detecter_type_document(titre)
            etablissement = extraire_etablissement(titre, type_doc)
            serie_cible = extraire_serie_cible(titre)
            matiere_suspecte = detecter_matiere_suspecte(titre)

            print(f"    Année={annee} | Séquence={sequence} | Type={type_doc} | "
                  f"Établissement={etablissement} | Série={serie_cible}"
                  + (" | ⚠️ MATIERE SUSPECTE" if matiere_suspecte else ""))

            nom_fichier = f"{annee}_{sequence or 'X'}_{total_trouvees}.pdf"
            chemin_local = PDF_DIR / nom_fichier

            succes = telecharger_pdf(lien_pdf, chemin_local)
            time.sleep(PAUSE_ENTRE_TELECHARGEMENTS)

            if not succes:
                print("    ❌ Échec du téléchargement PDF.")
                total_echecs += 1
                continue

            inserer_epreuve(conn, {
                "titre": titre,
                "annee": annee,
                "sequence": sequence,
                "type_document": type_doc,
                "etablissement": etablissement,
                "serie_cible": serie_cible,
                "matiere_suspecte": int(matiere_suspecte),
                "lien_pdf": lien_pdf,
                "lien_page": lien_page,
                "chemin_pdf_local": str(chemin_local),
            })
            total_telechargees += 1
            print(f"    ✅ Téléchargé -> {chemin_local}")

            if limite_test and total_telechargees >= limite_test:
                print(f"\n🛑 Limite de test atteinte ({limite_test} épreuves), arrêt.")
                conn.close()
                afficher_bilan(total_trouvees, total_telechargees, total_deja_en_base, total_echecs)
                return

        page += 1
        time.sleep(PAUSE_ENTRE_REQUETES)

    conn.close()
    afficher_bilan(total_trouvees, total_telechargees, total_deja_en_base, total_echecs)


def afficher_bilan(trouvees, telechargees, deja_en_base, echecs):
    print("\n" + "═" * 50)
    print("BILAN DU SCRAPING")
    print("═" * 50)
    print(f"  Épreuves trouvées      : {trouvees}")
    print(f"  Téléchargées avec succès : {telechargees}")
    print(f"  Déjà en base (ignorées)  : {deja_en_base}")
    print(f"  Échecs                   : {echecs}")
    print(f"  Base de données          : {DB_PATH}")
    print(f"  Dossier PDFs             : {PDF_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scraper RAG dédié — Maths Terminale C")
    parser.add_argument("--max-pages", type=int, default=15,
                         help="Nombre max de pages à parcourir (défaut: 15)")
    parser.add_argument("--limite-test", type=int, default=None,
                         help="S'arrête après N épreuves téléchargées (pour tester)")
    args = parser.parse_args()

    scraper_et_telecharger(max_pages=args.max_pages, limite_test=args.limite_test)