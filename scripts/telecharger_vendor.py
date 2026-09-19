# scripts/telecharger_vendor.py
import re
import urllib.request
from pathlib import Path

STATIC = Path("static")

def telecharger(url, dest, tentatives=3, user_agent=None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": user_agent} if user_agent else {}
    for i in range(tentatives):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as reponse:
                contenu = reponse.read()
            dest.write_bytes(contenu)
            print(f"OK  {dest} ({len(contenu)} octets)")
            return contenu
        except Exception as e:
            print(f"Tentative {i+1}/{tentatives} échouée pour {url} : {e}")
    print(f"ÉCHEC DÉFINITIF : {url}")
    return None

# --- marked.js et DOMPurify : fichiers uniques ---
telecharger(
    "https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js",
    STATIC / "vendor" / "marked.min.js"
)
telecharger(
    "https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.2.6/purify.min.js",
    STATIC / "vendor" / "purify.min.js"
)

# --- KaTeX : CSS + JS + auto-render + toutes les polices référencées ---
katex_dir = STATIC / "vendor" / "katex"
telecharger(
    "https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js",
    katex_dir / "katex.min.js"
)
telecharger(
    "https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/contrib/auto-render.min.js",
    katex_dir / "contrib" / "auto-render.min.js"
)
css_bytes = telecharger(
    "https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css",
    katex_dir / "katex.min.css"
)

if css_bytes:
    css_texte = css_bytes.decode("utf-8")
    polices = set(re.findall(r'url\((fonts/[^)]+?)\)', css_texte))
    for police in polices:
        nom_fichier = police.split("?")[0]
        telecharger(
            f"https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/{nom_fichier}",
            katex_dir / nom_fichier
        )
    print(f"{len(polices)} fichiers de police KaTeX téléchargés.")

# --- Google Fonts : User-Agent moderne pour avoir le woff2 ---
url_fonts_css = (
    "https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;"
    "9..144,600;9..144,700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600"
    "&family=Inter:wght@400;500;600;700&display=swap"
)
ua_moderne = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

fonts_dir = STATIC / "fonts"
fonts_css_bytes = telecharger(url_fonts_css, fonts_dir / "fonts_brut.css", user_agent=ua_moderne)

if fonts_css_bytes:
    fonts_css_texte = fonts_css_bytes.decode("utf-8")
    urls_polices = set(re.findall(r'url\((https://fonts\.gstatic\.com/[^)]+)\)', fonts_css_texte))
    for u in urls_polices:
        nom = u.split("/")[-1]
        telecharger(u, fonts_dir / nom)
        fonts_css_texte = fonts_css_texte.replace(u, nom)
    (fonts_dir / "fonts.css").write_text(fonts_css_texte, encoding="utf-8")
    (fonts_dir / "fonts_brut.css").unlink(missing_ok=True)
    print(f"{len(urls_polices)} fichiers de police Google téléchargés.")

print("\nTerminé.")