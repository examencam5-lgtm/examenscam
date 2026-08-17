"""
scripts/scrape_concourscameroon.py

Scrape les pages "anciennes epreuves" de concourscameroon.com pour BEPC,
Probatoire et BAC General.

MODE INDEXATION UNIQUEMENT — aucun PDF n'est telecharge ni reheberge.
Seuls titre, annee, niveau, serie, matiere et le LIEN EXTERNE sont
extraits. robots.txt verifie manuellement (voir conversation) :
seuls /?s=, /search/, /wp-json/ sont interdits — aucun blocage sur le
contenu lui-meme.

Sortie : data/scraped/concourscameroon.csv, meme format que
scrape_sigmaths.py, compatible avec import_liens_externes.py.

Usage :
    python scripts/scrape_concourscameroon.py

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
# CONFIG — liste des pages a scraper
# --------------------------------------------------------------------
# Chaque page correspond a UNE matiere (et parfois UNE serie) pour un
# niveau donne. Le champ "serie" ici est la valeur par defaut si le
# titre du lien PDF ne precise pas explicitement la serie (le parsing
# essaie d'abord d'extraire la serie directement du titre, plus fiable).

BASE = "https://www.concourscameroon.com"

PAGES = [
    # --- BEPC (15 matieres, pas de serie) ---
    {"url": f"{BASE}/anciennes-epreuves-allemand-de-lexamen.html", "niveau": "BEPC", "matiere": "Allemand", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-anglais-de-lexamen-2.html", "niveau": "BEPC", "matiere": "Anglais", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-composition.html", "niveau": "BEPC", "matiere": "Composition Francaise", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-education-la.html", "niveau": "BEPC", "matiere": "Education a la Citoyennete", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-espagnol-de-lexamen.html", "niveau": "BEPC", "matiere": "Espagnol", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-etude-de-texte-de_22.html", "niveau": "BEPC", "matiere": "Etude de Texte", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-expression-ecrite-de.html", "niveau": "BEPC", "matiere": "Expression Ecrite", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-geographie-de.html", "niveau": "BEPC", "matiere": "Geographie", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-histoire-de-lexamen.html", "niveau": "BEPC", "matiere": "Histoire", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-informatique-de.html", "niveau": "BEPC", "matiere": "Informatique", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-mathematics-de.html", "niveau": "BEPC", "matiere": "Mathematiques", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-orthographe-de.html", "niveau": "BEPC", "matiere": "Orthographe", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-chimie-physique.html", "niveau": "BEPC", "matiere": "PCT", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-redaction-de-lexamen.html", "niveau": "BEPC", "matiere": "Redaction", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-science-de-la-vie-et.html", "niveau": "BEPC", "matiere": "SVT", "serie": None},

    # --- Probatoire (20 matieres/series) ---
    {"url": f"{BASE}/anciennes-epreuves-dallemand-et.html", "niveau": "Probatoire", "matiere": "Allemand-Espagnol", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-danglais-au.html", "niveau": "Probatoire", "matiere": "Anglais", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-de-science-de-la-vie.html", "niveau": "Probatoire", "matiere": "SVT", "serie": "A"},
    {"url": f"{BASE}/anciennes-epreuves-de-science-de-la-vie_10.html", "niveau": "Probatoire", "matiere": "SVT", "serie": "D"},
    {"url": f"{BASE}/anciennes-epreuves-de-science-de-la-vie_18.html", "niveau": "Probatoire", "matiere": "SVT", "serie": "C-TI"},
    {"url": f"{BASE}/anciennes-epreuves-de-chimie-au.html", "niveau": "Probatoire", "matiere": "Chimie", "serie": "C-D"},
    {"url": f"{BASE}/anciennes-epreuves-deducation-la-2.html", "niveau": "Probatoire", "matiere": "Education a la Citoyennete", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-de-geographie-au.html", "niveau": "Probatoire", "matiere": "Geographie", "serie": "A-B"},
    {"url": f"{BASE}/anciennes-epreuves-de-geographie-au_10.html", "niveau": "Probatoire", "matiere": "Geographie", "serie": "CDE-TI"},
    {"url": f"{BASE}/anciennes-epreuves-de-histoire-au.html", "niveau": "Probatoire", "matiere": "Histoire", "serie": "A-B"},
    {"url": f"{BASE}/anciennes-epreuves-de-histoire-au_10.html", "niveau": "Probatoire", "matiere": "Histoire", "serie": "CDE-TI"},
    {"url": f"{BASE}/anciennes-epreuves-de-informatique-au.html", "niveau": "Probatoire", "matiere": "Informatique", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-de-litterature.html", "niveau": "Probatoire", "matiere": "Litterature-Francais", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-de-mathematiques-au.html", "niveau": "Probatoire", "matiere": "Mathematiques", "serie": "A"},
    {"url": f"{BASE}/anciennes-epreuves-de-mathematiques-au_10.html", "niveau": "Probatoire", "matiere": "Mathematiques", "serie": "C"},
    {"url": f"{BASE}/anciennes-epreuves-de-mathematiques-au_82.html", "niveau": "Probatoire", "matiere": "Mathematiques", "serie": "D"},
    {"url": f"{BASE}/anciennes-epreuves-de-physique-au.html", "niveau": "Probatoire", "matiere": "Physique", "serie": "A"},
    {"url": f"{BASE}/anciennes-epreuves-de-physique-au_10.html", "niveau": "Probatoire", "matiere": "Physique", "serie": "C-E"},
    {"url": f"{BASE}/anciennes-epreuves-de-physique-au_99.html", "niveau": "Probatoire", "matiere": "Physique", "serie": "D-TI"},
    {"url": f"{BASE}/anciennes-epreuves-de-physique-chemie.html", "niveau": "Probatoire", "matiere": "Physique-Chimie", "serie": None},

    # --- BAC General (26 matieres/series) ---
    {"url": f"{BASE}/anciennes-epreuves-danglais-au_14.html", "niveau": "BAC", "matiere": "Anglais", "serie": "A"},
    {"url": f"{BASE}/anciennes-epreuves-danglais-au_39.html", "niveau": "BAC", "matiere": "Anglais", "serie": "C-D"},
    {"url": f"{BASE}/anciennes-epreuves-de-science-de-la-vie_14.html", "niveau": "BAC", "matiere": "SVT", "serie": "C"},
    {"url": f"{BASE}/anciennes-epreuves-de-science-de-la-vie_69.html", "niveau": "BAC", "matiere": "SVT", "serie": "D"},
    {"url": f"{BASE}/anciennes-epreuves-de-chimie-au_14.html", "niveau": "BAC", "matiere": "Chimie", "serie": "C-D"},
    {"url": f"{BASE}/anciennes-epreuves-deducation-la_14.html", "niveau": "BAC", "matiere": "Education a la Citoyennete", "serie": "ABCDE"},
    {"url": f"{BASE}/anciennes-epreuves-deducation-la_86.html", "niveau": "BAC", "matiere": "Education a la Citoyennete", "serie": "ACDETI"},
    {"url": f"{BASE}/anciennes-epreuves-despagnol-et.html", "niveau": "BAC", "matiere": "Espagnol-Allemand", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-facultative-au.html", "niveau": "BAC", "matiere": "Facultative", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-de-francais-au_15.html", "niveau": "BAC", "matiere": "Francais", "serie": "ABI"},
    {"url": f"{BASE}/anciennes-epreuves-de-francais-au_34.html", "niveau": "BAC", "matiere": "Francais", "serie": "CD-E"},
    {"url": f"{BASE}/anciennes-epreuves-de-francais-au_3.html", "niveau": "BAC", "matiere": "Francais", "serie": "D-TI"},
    {"url": f"{BASE}/anciennes-epreuves-de-geographie-au_15.html", "niveau": "BAC", "matiere": "Geographie", "serie": "A-B"},
    {"url": f"{BASE}/anciennes-epreuves-de-geographie-au_21.html", "niveau": "BAC", "matiere": "Geographie", "serie": "CDE-TI"},
    {"url": f"{BASE}/anciennes-epreuves-de-geographie-au_62.html", "niveau": "BAC", "matiere": "Geographie", "serie": "BABCDE-TI"},
    {"url": f"{BASE}/anciennes-epreuves-de-histoire-au_15.html", "niveau": "BAC", "matiere": "Histoire", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-de-informatique-au_15.html", "niveau": "BAC", "matiere": "Informatique", "serie": None},
    {"url": f"{BASE}/anciennes-epreuves-de-mathematique-au.html", "niveau": "BAC", "matiere": "Mathematiques", "serie": "A"},
    {"url": f"{BASE}/anciennes-epreuves-de-mathematique-au_15.html", "niveau": "BAC", "matiere": "Mathematiques", "serie": "C"},
    {"url": f"{BASE}/anciennes-epreuves-de-mathematique-au_35.html", "niveau": "BAC", "matiere": "Mathematiques", "serie": "D"},
    {"url": f"{BASE}/anciennes-epreuves-de-philosophie-au.html", "niveau": "BAC", "matiere": "Philosophie", "serie": "A"},
    {"url": f"{BASE}/anciennes-epreuves-de-philosophie-au_15.html", "niveau": "BAC", "matiere": "Philosophie", "serie": "B"},
    {"url": f"{BASE}/anciennes-epreuves-de-philosophie-au_3.html", "niveau": "BAC", "matiere": "Philosophie", "serie": "CDE-TI"},
    {"url": f"{BASE}/anciennes-epreuves-de-physique-au_16.html", "niveau": "BAC", "matiere": "Physique", "serie": "C-E"},
    {"url": f"{BASE}/anciennes-epreuves-de-physique-au_51.html", "niveau": "BAC", "matiere": "Physique", "serie": "E-C"},
    {"url": f"{BASE}/anciennes-epreuves-de-physique-au_8.html", "niveau": "BAC", "matiere": "Physique", "serie": "D-TI"},
]

SOURCE_SITE = "concourscameroon"
OUTPUT_FILE = Path("data/scraped/concourscameroon.csv")

HEADERS = {
    "User-Agent": "ExamensCam-Indexeur/1.0 (+https://examenscam.onrender.com; contact: examenscam5@gmail.com)"
}

REQUEST_TIMEOUT = 25  # augmente de 15 a 25s -- plusieurs pages ont timeout a 15s
DELAY_BETWEEN_PAGES = 1.5  # secondes — courtoisie, 61 pages a la suite
MAX_RETRIES = 2


# --------------------------------------------------------------------
# PARSING
# --------------------------------------------------------------------

def parse_titre(text):
    """
    Extrait l'annee et, si present, la serie depuis le titre du lien.
    Deux formats rencontres sur ce site :
      - "Maths BEPC 2008.pdf"
      - "Mathématiques – Probatoire Série C – MINESEC – 2000.PDF"
    """
    m_annee = re.search(r'(19|20)\d{2}', text)
    annee = int(m_annee.group(0)) if m_annee else None

    m_serie = re.search(r'S[ée]rie\s+([A-Za-z0-9&\-]+)', text, re.IGNORECASE)
    serie_titre = m_serie.group(1) if m_serie else None

    return annee, serie_titre


def is_pdf_link(href, text):
    combined = (href + " " + text).lower()
    return ".pdf" in combined or "drive.google.com" in combined


def sanitiser_href(href):
    """
    Corrige deux problemes observes sur ce site :
    1. Certains hrefs sont concatenes plusieurs fois par erreur cote
       source (ex: 'https://drive...id=Xhttps://drive...id=Xhttps://drive...id=X')
       -> on ne garde que la premiere URL complete.
    2. Certains liens pointent vers la page d'accueil du site
       ('http://www.concourscameroon.com/') au lieu d'un vrai PDF --
       ce sont des liens casses cote source, pas exploitables.
    Retourne None si le lien est inexploitable (le caller doit alors
    ignorer la ligne).
    """
    href = href.strip()

    # Detecte une concatenation : la meme URL de base apparait 2+ fois
    m = re.match(r'^(https?://[^\s]+?)(?:https?://)', href)
    if m:
        href = m.group(1)

    # Rejette les liens qui ne pointent nulle part d'utile (homepage,
    # liens vides, ancres JS, etc.)
    parsed_path = re.sub(r'^https?://(www\.)?concourscameroon\.com/?$', '', href)
    if not parsed_path or href.lower() in ("http://www.concourscameroon.com/", "https://www.concourscameroon.com/"):
        return None

    return href


def parse_page(html, page_config):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)

        if not href or not is_pdf_link(href, text):
            continue

        href = sanitiser_href(href)
        if not href:
            continue

        annee, serie_titre = parse_titre(text)
        if not annee:
            continue  # pas d'annee identifiable -> on ignore cette ligne

        serie = serie_titre or page_config["serie"]

        titre = text if text else f"{page_config['matiere']} {page_config['niveau']} {annee}"

        results.append({
            "niveau": page_config["niveau"],
            "serie": serie,
            "matiere": page_config["matiere"],
            "annee": annee,
            "titre": titre,
            "lien_externe": href,
        })

    return results


# --------------------------------------------------------------------
# EXECUTION
# --------------------------------------------------------------------

def fetch_page(url):
    for tentative in range(1, MAX_RETRIES + 2):  # essai initial + retries
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except requests.exceptions.RequestException as e:
            if tentative <= MAX_RETRIES:
                print(f"  Tentative {tentative} echouee ({e}), nouvel essai...")
                time.sleep(3)
            else:
                print(f"  Erreur reseau apres {MAX_RETRIES + 1} essais ({e}) — page ignoree")
                return None


def write_csv(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["niveau", "serie", "matiere", "annee", "titre", "lien_externe", "source_site"]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            row_out = {k: row.get(k, "") for k in fieldnames}
            row_out["source_site"] = SOURCE_SITE
            writer.writerow(row_out)


def main():
    all_rows = []
    total_pages = len(PAGES)

    for i, page in enumerate(PAGES, 1):
        print(f"[{i}/{total_pages}] {page['niveau']} / {page['matiere']} ({page['serie'] or 'sans serie'})")
        html = fetch_page(page["url"])
        if html is None:
            continue

        rows = parse_page(html, page)
        print(f"  -> {len(rows)} sujets trouves")
        all_rows.extend(rows)

        time.sleep(DELAY_BETWEEN_PAGES)

    write_csv(all_rows, OUTPUT_FILE)

    print(f"\n{len(all_rows)} entrees ecrites dans {OUTPUT_FILE}")

    from collections import Counter
    par_niveau = Counter(r["niveau"] for r in all_rows)
    for niveau, count in par_niveau.items():
        print(f"  {niveau}: {count}")

    print("\nRappel : ce script n'a telecharge aucun PDF.")
    print("Etape suivante : python scripts/import_liens_externes.py data/scraped/concourscameroon.csv")


if __name__ == "__main__":
    main()