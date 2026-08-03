"""
scraper_epreuvesetcorriges.py — ExamensCam
Scrape epreuvesetcorriges.com via son sitemap XML (autorise par
robots.txt -- /categories/ n'est pas dans les Disallow).

Strategie : lit le sitemap une seule fois (pas de pagination
manuelle sur 60 pages par categorie), filtre les URLs Cameroun
BAC/Probatoire/BEPC, visite chaque page detail avec des headers de
navigateur reel + delai poli entre requetes, extrait titre + lien
PDF direct (pattern confirme : {url page}/download).

IMPORTANT : n'ecrit PAS directement en base. Ce site melange des
harmonises regionaux (-> annales_blanches) et des devoirs
d'etablissement (-> annales_externes), une distinction qu'un script
ne peut pas garantir a 100% -- le CSV de sortie est a relire
rapidement avant import, comme le pipeline Apps Script existant.

Usage :
    python scraper_epreuvesetcorriges.py
    (produit epreuvesetcorriges_brut.csv)
"""
import csv
import re
import time
import requests
from xml.etree import ElementTree

SITEMAP_URL = "https://epreuvesetcorriges.com/index.php?option=com_jmap&view=sitemap&format=xml"
OUTPUT_CSV = "epreuvesetcorriges_brut.csv"

# Headers de navigateur reel -- une requete avec le User-Agent par
# defaut de `requests` ("python-requests/2.x") est le premier signal
# qu'une protection anti-bot detecte. On se presente comme Chrome.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Delai entre chaque requete -- reste poli, evite de se faire bannir.
# 1.5s peut sembler lent sur 15000 documents mais on ne scrape QUE
# les categories qui nous interessent (BAC/Probatoire/BEPC Cameroun),
# pas tout le site.
DELAI_SECONDES = 1.5

# Seuls ces segments d'URL nous interessent (Cameroun, niveaux voulus)
PATTERNS_CIBLES = [
    "/categories/cameroun/examens/bac/",
    "/categories/cameroun/examens/probatoire/",
    "/categories/cameroun/examens/bepc/",
]


def recuperer_urls_sitemap():
    """Lit le sitemap XML, retourne la liste des URLs qui matchent nos categories cibles."""
    print("Telechargement du sitemap...")
    resp = requests.get(SITEMAP_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    root = ElementTree.fromstring(resp.content)
    # Le sitemap XML standard utilise un namespace -- necessaire pour que
    # ElementTree trouve les balises <loc> correctement
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    urls = []
    for url_elem in root.findall("sm:url", ns):
        loc = url_elem.find("sm:loc", ns)
        if loc is not None and loc.text:
            if any(pattern in loc.text for pattern in PATTERNS_CIBLES):
                urls.append(loc.text)

    print(f"{len(urls)} URLs trouvees dans les categories cibles.")
    return urls


def deviner_niveau(url):
    """Deduit BAC/Probatoire/BEPC depuis le segment d'URL."""
    if "/bac/" in url:
        return "BAC"
    if "/probatoire/" in url:
        return "Probatoire"
    if "/bepc/" in url:
        return "BEPC"
    return None


def extraire_titre(html):
    """Extrait le titre <h1> ou <title> de la page -- plus fiable que
    le slug de l'URL, qui peut etre tronque ou mal forme."""
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
    if match:
        # Nettoyage basique des balises HTML residuelles dans le titre
        return re.sub(r"<[^>]+>", "", match.group(1)).strip()
    return None


def deviner_annee(titre):
    """Cherche une annee plausible (2015-2027) dans le titre."""
    if not titre:
        return None
    match = re.search(r"\b(20[12]\d)\b", titre)
    return match.group(1) if match else None


def scraper():
    urls = recuperer_urls_sitemap()
    lignes = []

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            titre = extraire_titre(resp.text)

            lignes.append({
                "niveau_devine": deviner_niveau(url),
                "annee_devinee": deviner_annee(titre),
                "titre": titre or "",
                "lien_page_source": url,
                "lien_externe": url.rstrip("/") + "/download",
                "source_site": "epreuvesetcorriges",
            })
        except requests.RequestException as e:
            print(f"  Erreur : {e}")

        time.sleep(DELAI_SECONDES)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "niveau_devine", "annee_devinee", "titre",
            "lien_page_source", "lien_externe", "source_site"
        ])
        writer.writeheader()
        writer.writerows(lignes)

    print(f"\n{len(lignes)} lignes ecrites dans {OUTPUT_CSV}")
    print("Relis le CSV avant import -- classe manuellement chaque ligne")
    print("en 'blanche' (harmonise regional) ou 'externe' (devoir etablissement)")
    print("selon le titre, puis adapte le script d'import en consequence.")


if __name__ == "__main__":
    scraper()