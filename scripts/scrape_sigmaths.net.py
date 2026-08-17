"""
scripts/scrape_sigmaths.py

Scrape la page "Sujets de mathematiques au baccalaureat Camerounais" de
sigmaths.net (bac2/Cameroun.php).

MODE INDEXATION UNIQUEMENT — aucun PDF n'est telecharge ni reheberge.
Seuls le titre, l'annee, le niveau, la serie et le LIEN EXTERNE sont
extraits. L'utilisateur final est redirige vers sigmaths.net pour
consulter le PDF. Ce choix est deliberement conservateur d'un point de
vue legal (voir charte d'utilisation sigmaths.net : reproduction /
diffusion en ligne du contenu interdite).

Sortie : un CSV dans data/scraped/, pret pour scripts/import_liens_externes.py

Usage :
    python scripts/scrape_sigmaths.py

Dependances :
    pip install requests beautifulsoup4 --break-system-packages
"""

import csv
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------

URL_CAMEROUN = "https://www.sigmaths.net/bac2/Cameroun.php"
SOURCE_SITE = "sigmaths"
MATIERE = "Mathematiques"  # cette page ne couvre que les maths

OUTPUT_DIR = Path("data/scraped")
OUTPUT_FILE = OUTPUT_DIR / "sigmaths_cameroun.csv"

HEADERS = {
    "User-Agent": "ExamensCam-Indexeur/1.0 (+https://examenscam.onrender.com; contact: examenscam5@gmail.com)"
}

REQUEST_TIMEOUT = 15  # secondes — Maroua = reseau instable, on ne bloque pas indefiniment


# --------------------------------------------------------------------
# PARSING
# --------------------------------------------------------------------

def parse_serie(label):
    """Nettoie une etiquette de serie brute en retirant le prefixe 'Serie(s)'."""
    label = label.strip()
    label = re.sub(r'^S[ée]ries?\s*', '', label, flags=re.IGNORECASE)
    return label.strip(" :-")


def is_probatoire(text):
    return bool(re.search(r'probatoire', text, re.IGNORECASE))


def is_bepc(text):
    return bool(re.search(r'\bBEPC\b', text, re.IGNORECASE))


def classify_type(text, href):
    """Determine si le lien pointe vers un sujet, un corrige, ou les deux.
    Utilise uniquement pour enrichir le titre — annales_externes n'a pas
    de colonne dediee, l'info reste donc visible dans le titre affiche."""
    combined = (text + " " + href).lower()
    has_corrige = bool(re.search(r'corrig|correction', combined))
    has_sujet = bool(re.search(r'sujet|enonc', combined)) or not has_corrige
    if has_sujet and has_corrige:
        return "sujet_corrige"
    if has_corrige:
        return "corrige"
    return "sujet"


def parse_page(html):
    """
    Parcourt les tableaux de la page Cameroun et retourne une liste de
    dictionnaires structures (un par lien PDF trouve).

    Structure de la page : plusieurs <table>, chacune commencant par une
    ligne d'en-tete "Annee XXXX" (ou "Plus ancien" pour les tres vieux
    sujets, ou l'annee est encodee inline dans le libelle, ex: "A(2001)").
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for table in soup.find_all("table"):
        current_annee = None

        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if not cells:
                continue

            header_text = cells[0].get_text(strip=True)

            m_annee = re.search(r'Ann[ée]e\s*(\d{4})', header_text, re.IGNORECASE)
            if m_annee:
                current_annee = int(m_annee.group(1))
                continue

            if header_text.lower().startswith("plus ancien"):
                current_annee = None
                continue

            links = tr.find_all("a")
            if not links:
                continue

            if len(cells) == 1:
                for a in links:
                    text = a.get_text(strip=True)
                    href = a.get("href", "")
                    if not href:
                        continue
                    niveau = "BEPC" if is_bepc(text) else ("Probatoire" if is_probatoire(text) else "BAC")
                    serie_match = re.search(r'S[ée]ries?\s+([A-Za-z0-9\-/,]+)', text, re.IGNORECASE)
                    serie = parse_serie(serie_match.group(0)) if serie_match else None
                    results.append({
                        "annee": current_annee,
                        "niveau": niveau,
                        "serie": serie,
                        "matiere": MATIERE,
                        "type_sujet": classify_type(text, href),
                        "titre": text,
                        "lien_externe": href,
                    })
            else:
                serie_label = cells[0].get_text(strip=True)
                m_inline = re.match(r'([A-Za-z\-]+)\((\d{4})\)', serie_label)
                annee = current_annee
                serie_raw = serie_label
                if m_inline:
                    serie_raw = m_inline.group(1)
                    annee = int(m_inline.group(2))

                niveau = "BEPC" if is_bepc(serie_label) else ("Probatoire" if is_probatoire(serie_label) else "BAC")

                for a in links:
                    text = a.get_text(strip=True)
                    href = a.get("href", "")
                    if not href:
                        continue
                    results.append({
                        "annee": annee,
                        "niveau": niveau,
                        "serie": parse_serie(serie_raw),
                        "matiere": MATIERE,
                        "type_sujet": classify_type(text, href),
                        "titre": f"{serie_label} {text}".strip(),
                        "lien_externe": href,
                    })

    return results


# --------------------------------------------------------------------
# EXECUTION
# --------------------------------------------------------------------

def fetch_page(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        # IMPORTANT : ne pas utiliser resp.apparent_encoding (chardet devine
        # souvent mal sur ce type de page et produit du mojibake -> "SÃ©rie").
        # Les headers HTTP de sigmaths.net annoncent explicitement UTF-8,
        # on le force donc directement.
        resp.encoding = "utf-8"
        return resp.text
    except requests.exceptions.RequestException as e:
        print(f"Erreur reseau lors du fetch de {url} : {e}")
        sys.exit(1)


def write_csv(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["niveau", "serie", "matiere", "annee", "type_sujet", "titre", "lien_externe", "source_site"]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            row_out = {k: row.get(k, "") for k in fieldnames}
            row_out["source_site"] = SOURCE_SITE
            writer.writerow(row_out)


def main():
    print(f"Fetch : {URL_CAMEROUN}")
    html = fetch_page(URL_CAMEROUN)

    print("Parsing...")
    rows = parse_page(html)

    rows_valides = [r for r in rows if r["annee"] and r["lien_externe"]]
    rejetees = len(rows) - len(rows_valides)

    write_csv(rows_valides, OUTPUT_FILE)

    print(f"\n{len(rows_valides)} entrees ecrites dans {OUTPUT_FILE}")
    if rejetees:
        print(f"{rejetees} lignes rejetees (annee ou lien manquant) — a verifier manuellement si besoin")

    from collections import Counter
    par_niveau = Counter(r["niveau"] for r in rows_valides)
    for niveau, count in par_niveau.items():
        print(f"  {niveau}: {count}")

    print("\nRappel : ce script n'a telecharge aucun PDF. Les liens pointent vers sigmaths.net.")
    print("Etape suivante : python scripts/import_liens_externes.py data/scraped/sigmaths_cameroun.csv")

    time.sleep(1)


if __name__ == "__main__":
    main()