"""
scraper_mongosukulu.py — ExamensCam (v2, exploration recursive)
Scrape mongosukulu.com. Structure decouverte irreguliere :
  - BEPC : /telechargement/bepc/BEPC2021/  (2 niveaux)
  - BAC/Probatoire : /telechargement/bac/bactechnique/...
                      /telechargement/probatoire/probatoiregeneral/probatoire2015/
                      (3 niveaux, ET le nommage du dossier annee varie
                      d'une annee a l'autre : 'probatoire2015',
                      'Probatoire-technique-2011', 'probatoiretechnique2017')

Plutot que de deviner un pattern fixe (fragile, casse a la premiere
exception), on explore RECURSIVEMENT : sur chaque page, si on trouve
de vrais fichiers (titres <h3>/<h2> avec lien detail), on les prend.
Sinon, on considere que ce sont des sous-dossiers et on descend dedans.
Profondeur max 4 pour eviter toute boucle infinie.

IMPORTANT : ne visite jamais le lien de telechargement reel
(func-startdown/<id>) -- limite de 10 telechargements/24h sur le
site, et notre strategie est indexation + redirection uniquement.

Usage :
    python scraper_mongosukulu.py
    (produit mongosukulu_brut.csv)
"""
import csv
import re
import time
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup

BASE = "https://www.mongosukulu.com"
OUTPUT_CSV = "mongosukulu_brut.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

DELAI_SECONDES = 1.2
PROFONDEUR_MAX = 4

CATEGORIES_CIBLES = {
    "bepc": "BEPC",
    "bac": "BAC",
    "probatoire": "Probatoire",
}

PATTERNS_IGNORES = ["orderby,", "/search/", "func-addfile", "func-startdown", "/contact", "/a-propos"]


def get(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def normaliser_url(href):
    """
    Certains liens du site omettent 'www.' (mongosukulu.com au lieu
    de www.mongosukulu.com) -- normalise tout vers la meme forme pour
    que la comparaison de prefixe ne rejette pas ces liens a tort.
    C'est ce qui causait la chute de 81 a 18 lignes trouvees.
    """
    if href.startswith("http"):
        parsed = urlparse(href)
        return f"https://www.mongosukulu.com{parsed.path}"
    return BASE + href


def est_lien_utile(href, prefixe_categorie):
    if not href.startswith(prefixe_categorie):
        return False
    if any(p in href for p in PATTERNS_IGNORES):
        return False
    return True


def extraire_fichiers_page(soup):
    fichiers = []
    for h in soup.find_all(["h2", "h3"]):
        a = h.find("a", href=True)
        if a and "/telechargement/" in a["href"]:
            titre = a.get_text(strip=True)
            lien = normaliser_url(a["href"])
            fichiers.append((titre, lien))
    return fichiers


def extraire_sous_liens(soup, prefixe_categorie):
    liens = set()
    for a in soup.find_all("a", href=True):
        href_complet = normaliser_url(a["href"])
        if est_lien_utile(href_complet, prefixe_categorie):
            liens.add(href_complet.rstrip("/") + "/")
    return liens


def est_page_de_fichiers(soup):
    """
    Remository (Joomla) affiche les DOSSIERS avec exactement la meme
    structure HTML (<h3> + lien) que les FICHIERS -- impossible de
    les distinguer par la structure seule. Mais seule une page de
    vrais fichiers affiche 'Taille :' (poids du fichier), absent sur
    une page de listing de sous-dossiers. C'est le signal fiable.
    """
    return "Taille :" in soup.get_text()


def explorer(url, prefixe_categorie, profondeur, deja_visites, resultats):
    if profondeur > PROFONDEUR_MAX or url in deja_visites:
        return
    deja_visites.add(url)

    try:
        soup = get(url)
    except requests.RequestException as e:
        print(f"  {'  ' * profondeur}Erreur {url} : {e}")
        return

    if est_page_de_fichiers(soup):
        fichiers = extraire_fichiers_page(soup)
        print(f"  {'  ' * profondeur}{len(fichiers)} fichier(s) sur {url}")
        resultats.extend(fichiers)
        time.sleep(DELAI_SECONDES)

        # Pagination -- une annee avec beaucoup de fichiers peut etre
        # decoupee en plusieurs pages ("Page: 1 2 Suivant »"). Sans
        # ca, les fichiers des pages 2+ seraient perdus silencieusement.
        lien_suivant = None
        for a in soup.find_all("a", href=True):
            if "suivant" in a.get_text(strip=True).lower():
                lien_suivant = normaliser_url(a["href"])
                break
        if lien_suivant and lien_suivant not in deja_visites:
            explorer(lien_suivant, prefixe_categorie, profondeur, deja_visites, resultats)
        return

    # Pas de 'Taille :' -- ce sont des sous-dossiers, on descend dedans
    sous_liens = extraire_sous_liens(soup, prefixe_categorie)
    print(f"  {'  ' * profondeur}{len(sous_liens)} sous-dossier(s) sur {url}")
    time.sleep(DELAI_SECONDES)

    for lien in sous_liens:
        explorer(lien, prefixe_categorie, profondeur + 1, deja_visites, resultats)


def extraire_lien_telechargement(html):
    match = re.search(r'href="([^"]*func-startdown[^"]*)"', html)
    return match.group(1) if match else None


def deviner_annee(titre):
    match = re.search(r"\b(20[01]\d|19[89]\d)\b", titre)
    return match.group(1) if match else None


def scraper():
    toutes_lignes = []

    for slug, niveau in CATEGORIES_CIBLES.items():
        print(f"\n=== {niveau} ({slug}) ===")
        url_racine = f"{BASE}/index.php/telechargement/{slug}/"
        prefixe = f"{BASE}/index.php/telechargement/{slug}/"

        fichiers_trouves = []
        explorer(url_racine, prefixe, 0, set(), fichiers_trouves)
        print(f"Total fichiers trouves pour {niveau} : {len(fichiers_trouves)}")

        for titre, lien_detail in fichiers_trouves:
            try:
                resp = requests.get(lien_detail, headers=HEADERS, timeout=20)
                resp.raise_for_status()
                lien_pdf = extraire_lien_telechargement(resp.text)
            except requests.RequestException as e:
                print(f"    Erreur detail : {e}")
                lien_pdf = None

            lien_externe = normaliser_url(lien_pdf) if lien_pdf else ""

            toutes_lignes.append({
                "niveau_devine": niveau,
                "annee_devinee": deviner_annee(titre),
                "titre": titre,
                "lien_page_source": lien_detail,
                "lien_externe": lien_externe,
                "source_site": "mongosukulu",
            })
            time.sleep(DELAI_SECONDES)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "niveau_devine", "annee_devinee", "titre",
            "lien_page_source", "lien_externe", "source_site"
        ])
        writer.writeheader()
        writer.writerows(toutes_lignes)

    print(f"\n{len(toutes_lignes)} lignes ecrites dans {OUTPUT_CSV}")


if __name__ == "__main__":
    scraper()
