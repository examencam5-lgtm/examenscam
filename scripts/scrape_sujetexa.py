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
# Chaque "niveau/série" correspond à plusieurs sous-catégories matière
# sur sujetexa. On a extrait ça manuellement depuis leur menu de navigation.
# Le nom de matière (clé) sera stocké tel quel dans le CSV.

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
        "Philosophie": "ecm_pa", # à vérifier : ECM vs Philo selon année du programme
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
        "Mathematiques": "terminale-a/maths_ta",
        "Francais": "francais_ta",
        "Anglais": "anglais_ta",
        "Informatique": "informatique_ta",
        "Geographie": "geographie_ta",
        "Histoire": "histoire_ta",
        "SVT": "svt_ta",
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

# Nombre max de pages à parcourir par sous-catégorie avant d'abandonner
# (évite de scraper les 1020 pages du site si l'année n'est pas trouvée)
MAX_PAGES = 15


def extraire_annee(titre: str) -> int | None:
    """
    Cherche une année plausible (1990-2026) dans le titre d'un article.
    Priorité aux formats 'SESSION 2021' ou '-2021' en fin de titre.
    """
    matches = re.findall(r'(19[9]\d|20[0-2]\d)', titre)
    if not matches:
        return None
    # On prend la dernière année trouvée (souvent la plus pertinente,
    # ex: "COLLEGE MONGO BETI...2025/2026" -> on veut 2026 ou 2025 selon contexte)
    return int(matches[-1])


def extraire_lien_pdf_article(page_url: str) -> str:
    """
    Visite la page d'un article individuel et en extrait le lien PDF réel.

    Sur sujetexa, la page de catégorie (liste) ne contient PAS le lien PDF,
    seulement le titre. Le vrai lien est sur la page de l'article, sous la
    forme d'une image cliquable : [![](thumbnail)](URL_DU_PDF.pdf)

    On cherche simplement le premier <a> dont le href finit par '.pdf' —
    dans la sidebar, le seul lien "fichier" pointe vers Google Drive (pas .pdf),
    donc ce filtre n'attrape pas de faux positifs.
    """
    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f" ⚠️ Erreur sur la page article {page_url} : {e}")
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf"):
            return href

    return "" # Aucun PDF trouvé sur cette page


def scraper_categorie(matiere: str, slug: str, annee_cible: int) -> list[dict]:
    """
    Parcourt une sous-catégorie (une matière) page par page.

    ÉTAPE 1 : sur chaque page de liste, on repère les articles dont le
    titre contient l'année cible (rapide, une seule requête par page).

    ÉTAPE 2 : pour CHAQUE article retenu, on visite sa page individuelle
    pour en extraire le vrai lien PDF (une requête par article pertinent
    seulement — pas pour tous les articles, ce qui limiterait le volume
    de requêtes).
    """
    articles_pertinents = [] # (titre, annee, lien_page)
    page = 1

    while page <= MAX_PAGES:
        url = f"{BASE_URL}/{slug}/" if page == 1 else f"{BASE_URL}/{slug}/page/{page}/"

        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
        except requests.RequestException as e:
            print(f" ⚠️ Erreur réseau sur {url} : {e}")
            break

        if resp.status_code == 404:
            break # Catégorie ou page inexistante -> fin propre
        if resp.status_code != 200:
            print(f" ⚠️ Statut {resp.status_code} sur {url}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = soup.find_all("h2")
        if not articles:
            break # Plus d'articles -> fin de la catégorie

        for h2 in articles:
            lien_titre = h2.find("a")
            if not lien_titre:
                continue
            titre = lien_titre.get_text(strip=True)
            annee_detectee = extraire_annee(titre)

            if annee_detectee == annee_cible:
                articles_pertinents.append((titre, annee_detectee, lien_titre.get("href", "")))

        page += 1
        time.sleep(1) # Politesse entre les pages de catégorie

    # ÉTAPE 2 : récupérer le vrai lien PDF pour chaque article retenu
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
        time.sleep(1) # Politesse entre chaque article

    return resultats


def scraper_niveau_serie_annee(niveau_serie: str, annee: int) -> list[dict]:
    """
    Point d'entrée principal : scrape toutes les matières
    d'un niveau/série pour une année donnée.
    """
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
    """Écrit les résultats dans un CSV prêt à être vérifié puis importé."""
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

