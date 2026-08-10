   # scripts/scrape_sujetexa.py
"""
Scrape les liens PDF de sujetexa.com pour un niveau/série/année donné.
On ne télécharge RIEN : on récupère uniquement les URLs des PDFs,
qui restent hébergés chez sujetexa. On indexe, on ne copie pas.

Usage :
    python scrape_sujetexa.py terminale-c 2021
    python scrape_sujetexa.py troisieme 2023

Sortie : un CSV dans data/liens_externes/ avec les colonnes
niveau, serie, matiere, annee, titre, lien_pdf, lien_page, source

MODIFICATION (recree apres suppression accidentelle + episode de
coupures DNS repetees le meme jour) : ajout d'un retry automatique
sur les erreurs reseau (jusqu'a 3 tentatives, avec pause entre
chaque), pour ne pas perdre toute une session de scraping a cause
d'une coupure de quelques secondes -- frequent avec la connexion a
Maroua.
"""

import re
import csv
import sys
import time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════
# 1. MAPPING DES CATÉGORIES SUJETEXA
# ═══════════════════════════════════════════════════════

CATEGORIES = {
    "troisieme": {
        "Mathematiques": "maths",
        "Francais": "francais_3",
        "Anglais": "anglais_3",
        "ECM": "ecm_3",
        "Informatique": "informatique_3",
        "Geographie": "geographie_3",
        "Histoire": "histoire_3",
        "PCT": "pct_3",
        "SVT": "svt_3",
    },
    "premiere-a": {
        "Mathematiques": "premiere-a/maths_pa",
        "Francais": "francais_pa",
        "Anglais": "anglais_pa",
        "Informatique": "informatique_pa",
        "Philosophie": "ecm_pa",
        "Geographie": "geographie_pa",
        "Histoire": "histoire_pa",
        "Physique-Chimie": "phy-chim_pa",
        "SVT": "svt_pa",
    },
    "premiere-c": {
        "Francais": "francais_pc",
        "Mathematiques": "maths_pc",
        "Anglais": "anglais_pc",
        "Informatique": "informatique_pc",
        "Chimie": "chimie_pc",
        "Geographie": "geographie_pc",
        "Histoire": "histoire_pc",
        "Physique": "physique_pc",
        "SVT": "svt_pc",
    },
    "premiere-d": {
        "Mathematiques": "maths_pd",
        "Francais": "francais_pd",
        "Anglais": "anglais_pd",
        "Chimie": "chimie_pd",
        "Geographie": "geographie_pd",
        "Histoire": "histoire_pd",
        "Physique": "physique_pd",
        "SVT": "svt_pd",
        "Informatique": "informatique_pd",
    },
    "terminale-a": {
        "Litterature": "francais_ta",
        "Philosophie": "philosophie_ta",
        "Allemand": "allemand_ta",
        "Espagnol": "espagnol_ta"
    },
    "terminale-c": {
        "Mathematiques": "terminale-c/maths_tc",
        "Francais": "francais_tc",
        "Anglais": "anglais_tc",
        "Chimie": "chimie_tc",
        "Informatique": "informatique_tc",
        "Geographie": "geographie_tc",
        "Histoire": "histoire_tc",
        "Physique": "physique_tc",
        "SVT": "svt_tc",
    },
    "terminale-d": {
        "Mathematiques": "terminale-d/maths_td",
        "Francais": "francais_td",
        "Anglais": "anglais_td",
        "Informatique": "informatique_td",
        "Chimie": "chimie_td",
        "Histoire": "histoire_td",
        "Physique": "physique_td",
        "SVT": "svt_td",
    },
}

BASE_URL = "https://sujetexa.com/index.php/category"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExamensCamBot/1.0)"}
MAX_PAGES = 15

# Retry -- nombre de tentatives et pause entre chaque, sur toute
# erreur reseau (DNS, timeout, connexion refusee). Une coupure de
# quelques secondes ne doit plus faire planter toute la session.
MAX_TENTATIVES = 3
PAUSE_ENTRE_TENTATIVES = 5


def requete_avec_retry(url, description=""):
    """
    Fait une requete GET avec jusqu'a MAX_TENTATIVES essais en cas
    d'erreur reseau. Retourne la Response si succes, None si les
    trois tentatives echouent (l'appelant doit gerer ce cas -- ne
    jamais laisser planter tout le script pour UNE page qui echoue).
    """
    for tentative in range(1, MAX_TENTATIVES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            return resp
        except requests.exceptions.ConnectionError as e:
            print(f" ⚠️ Tentative {tentative}/{MAX_TENTATIVES} echouee ({description or url}) : {e}")
            if tentative < MAX_TENTATIVES:
                print(f"    Nouvelle tentative dans {PAUSE_ENTRE_TENTATIVES}s...")
                time.sleep(PAUSE_ENTRE_TENTATIVES)
        except requests.exceptions.Timeout:
            print(f" ⚠️ Timeout tentative {tentative}/{MAX_TENTATIVES} ({description or url})")
            if tentative < MAX_TENTATIVES:
                time.sleep(PAUSE_ENTRE_TENTATIVES)
    print(f" ❌ Abandon apres {MAX_TENTATIVES} tentatives : {description or url}")
    return None


def extraire_annee(titre: str) -> int | None:
    matches = re.findall(r'(19[9]\d|20[0-2]\d)', titre)
    if not matches:
        return None
    return int(matches[-1])


def extraire_lien_pdf_article(page_url: str) -> str:
    resp = requete_avec_retry(page_url, "page article")
    if resp is None:
        return ""
    if resp.status_code != 200:
        print(f" ⚠️ Statut {resp.status_code} sur {page_url}")
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf"):
            return href

    return ""


def scraper_categorie(matiere: str, slug: str, annee_cible: int) -> list[dict]:
    articles_pertinents = []
    page = 1
    echecs_consecutifs = 0

    while page <= MAX_PAGES:
        url = f"{BASE_URL}/{slug}/" if page == 1 else f"{BASE_URL}/{slug}/page/{page}/"

        resp = requete_avec_retry(url, f"page {page} de {slug}")
        if resp is None:
            echecs_consecutifs += 1
            # Si 2 pages d'affilee echouent completement (pas juste
            # un 404 normal), le site ou le reseau a un vrai probleme
            # -- inutile d'insister sur les 13 pages restantes
            if echecs_consecutifs >= 2:
                print(f" ❌ Deux echecs consecutifs sur {slug}, abandon de cette matiere.")
                break
            page += 1
            continue
        echecs_consecutifs = 0

        if resp.status_code == 404:
            break
        if resp.status_code != 200:
            print(f" ⚠️ Statut {resp.status_code} sur {url}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = soup.find_all("h2")
        if not articles:
            break

        for h2 in articles:
            lien_titre = h2.find("a")
            if not lien_titre:
                continue
            titre = lien_titre.get_text(strip=True)
            annee_detectee = extraire_annee(titre)

            if annee_detectee == annee_cible:
                articles_pertinents.append((titre, annee_detectee, lien_titre.get("href", "")))

        page += 1
        time.sleep(1)

    resultats = []
    for titre, annee, lien_page in articles_pertinents:
        lien_pdf = extraire_lien_pdf_article(lien_page)
        resultats.append({
            "matiere": matiere,
            "annee": annee,
            "titre": titre,
            "lien_pdf": lien_pdf,
            "lien_page": lien_page,
        })
        time.sleep(1)

    return resultats


def scraper_niveau_serie_annee(niveau_serie: str, annee: int) -> list[dict]:
    if niveau_serie not in CATEGORIES:
        print(f"❌ Niveau/série inconnu : {niveau_serie}")
        print(f" Options valides : {list(CATEGORIES.keys())}")
        return []

    tous_resultats = []
    matieres = CATEGORIES[niveau_serie]

    print(f"\n🔍 Scraping {niveau_serie} — année {annee}")
    print(f" {len(matieres)} matières à parcourir\n")

    for matiere, slug in matieres.items():
        print(f" → {matiere} ({slug})...")
        resultats = scraper_categorie(matiere, slug, annee)
        print(f" {len(resultats)} épreuve(s) trouvée(s)")
        tous_resultats.extend(resultats)

    return tous_resultats


def sauvegarder_csv(resultats: list[dict], niveau_serie: str, annee: int):
    output_dir = Path("data/liens_externes")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"sujetexa_{niveau_serie}_{annee}.csv"

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "matiere", "annee", "titre", "lien_pdf", "lien_page"
        ])
        writer.writeheader()
        writer.writerows(resultats)

    print(f"\n✅ {len(resultats)} lignes écrites dans {output_path}")
    print(" Vérifie le CSV avant import (liens vides, doublons, titres bizarres)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage : python scrape_sujetexa.py <niveau-serie> <annee>")
        print(f"Options niveau-serie : {list(CATEGORIES.keys())}")
        sys.exit(1)

    niveau_serie_arg = sys.argv[1]
    annee_arg = int(sys.argv[2])

    resultats = scraper_niveau_serie_annee(niveau_serie_arg, annee_arg)
    sauvegarder_csv(resultats, niveau_serie_arg, annee_arg)