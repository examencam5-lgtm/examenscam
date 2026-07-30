# verifier_tout.py
"""
Script de diagnostic : vérifie que tous les fichiers de la session
d'aujourd'hui sont bien en place et s'importent sans erreur.
Ne modifie rien, ne fait que tester.

Usage : python verifier_tout.py
"""

import sys
import re
import ast
import sqlite3
from pathlib import Path
# ═══════════════════════════════════════
# AJOUTS — diagnostic statique de app.py
# (à coller après les imports existants, avant "resultats = []" ou juste après)
# ═══════════════════════════════════════

import re
import ast


def lire_app():
    return Path("app.py").read_text(encoding="utf-8")


def test_routes_dupliquees():
    src = lire_app()
    chemins = re.findall(r"@app\.route\(\s*['\"]([^'\"]+)['\"]", src)
    vus = {}
    for c in chemins:
        vus[c] = vus.get(c, 0) + 1
    doublons = [f"{chemin} ({n} fois)" for chemin, n in vus.items() if n > 1]
    assert not doublons, f"Routes dupliquées : {doublons}"


def test_fonctions_importees_existent():
    src = lire_app()
    imports = re.findall(r"from (\w+) import \(?([^)\n]+)\)?", src)
    manquants = []
    for module, noms in imports:
        chemin_module = Path(f"{module}.py")
        if not chemin_module.exists():
            manquants.append(f"{module}.py introuvable (importé dans app.py)")
            continue
        contenu_module = chemin_module.read_text(encoding="utf-8")
        arbre = ast.parse(contenu_module)
        definis = {
            n.name for n in ast.walk(arbre)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        definis |= {
            cible.id for n in ast.walk(arbre) if isinstance(n, ast.Assign)
            for cible in n.targets if isinstance(cible, ast.Name)
        }
        for nom in [n.strip() for n in noms.split(",") if n.strip()]:
            if nom not in definis:
                manquants.append(f"{module}.{nom} importé dans app.py mais introuvable dans {module}.py")
    assert not manquants, f"{manquants}"


def test_categorie_colonne():
    db_path = Path('data') / 'annales.db'
    if not db_path.exists():
        return  # pas bloquant si la base n'est pas encore générée localement
    conn = sqlite3.connect(db_path)
    colonnes_packs = {r[1] for r in conn.execute("PRAGMA table_info(packs_corriges)").fetchall()}
    conn.close()
    problemes = []
    for fichier in ["app.py", "database_carrefour.py", "database_corriges.py"]:
        chemin = Path(fichier)
        if not chemin.exists():
            continue
        src = chemin.read_text(encoding="utf-8")
        if ("p.categorie" in src) or ("packs_corriges" in src and "categorie" in src):
            if "categorie" not in colonnes_packs:
                problemes.append(f"{fichier} référence 'categorie', absente du schéma réel ({sorted(colonnes_packs)})")
    assert not problemes, "; ".join(problemes)


def test_montant_paiement_coherent():
    src = lire_app()
    montants_en_dur = re.findall(r"montant.{0,40}?(\d{3,6})", src, re.IGNORECASE)
    if montants_en_dur:
        print(f" ⚠️ Montant(s) codé(s) en dur détecté(s) : {montants_en_dur} -- à vérifier vs packs_corriges.prix")


def test_imports_flask_redondants():
    src = lire_app()
    lignes_import = re.findall(r"^from flask import (.+)$", src, re.MULTILINE)
    tout, doublons = [], []
    for ligne in lignes_import:
        for n in [x.strip() for x in ligne.split(",")]:
            if n in tout:
                doublons.append(n)
            tout.append(n)
    assert not doublons, f"Imports Flask redondants : {sorted(set(doublons))}"

resultats = []

def tester(nom, fonction):
    try:
        fonction()
        resultats.append((nom, True, ""))
        print(f"✅ {nom}")
    except Exception as e:
        resultats.append((nom, False, str(e)))
        print(f"❌ {nom} : {e}")


def test_database_corriges():
    from database_corriges import creer_pack, get_packs_catalogue
    get_packs_catalogue()

def test_database_blanches():
    from database_blanches import get_epreuves_blanches, get_regions_disponibles
    get_epreuves_blanches("BAC", "Mathematiques", serie="C")

def test_database_carrefour():
    from database_carrefour import get_carrefour
    get_carrefour("BAC", "Mathematiques", serie="C")

def test_database_externes():
    from database_externes import get_matieres_externes, get_annales_externes
    get_matieres_externes("terminale-c")

def test_parser_titre():
    sys.path.insert(0, "scripts")
    from parser_titre_sujetexa import parser_titre
    resultat = parser_titre("MATHEMATIQUES-DRES DE LOUEST-SEQUENCE 4-FEVRIER 2026-TLEC")
    assert resultat["region"] == "OUEST", f"Bug région : {resultat}"

def test_tables_existent():
    import sqlite3
    from pathlib import Path
    conn = sqlite3.connect(Path('data') / 'annales.db')
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    attendues = ['annales', 'annales_externes', 'annales_blanches',
                 'packs_corriges', 'corriges_fichiers']
    manquantes = [t for t in attendues if t not in tables]
    assert not manquantes, f"Tables manquantes : {manquantes}"
    conn.close()

def test_templates_existent():
    from pathlib import Path
    attendus = [
        'carrefour.html', 'blancs_liste.html', 'corriges_catalogue.html',
        'corriges_fiche.html', 'etablissements_index.html',
        'etablissements_niveau.html', 'etablissements_matiere.html'
    ]
    manquants = [t for t in attendus if not (Path('templates') / t).exists()]
    assert not manquants, f"Templates manquants : {manquants}"


def test_css_existe():
    from pathlib import Path
    assert (Path('static') / 'css' / 'nouvelles_pages.css').exists(), "CSS manquant"
def test_fonctions_importees_existent():
    src = lire_app()
    # Gère aussi les imports multi-lignes entre parenthèses
    imports = re.findall(r"from (\w+) import\s*\(([^)]+)\)|from (\w+) import ([^\n(]+)", src)
    manquants = []
    for m in imports:
        module = m[0] or m[2]
        noms_bruts = m[1] or m[3]
        chemin_module = Path(f"{module}.py")
        if not chemin_module.exists():
            continue  # bibliothèque standard/tierce (flask, pathlib, io, datetime...) — pas un fichier local, on ignore
        contenu_module = chemin_module.read_text(encoding="utf-8")
        arbre = ast.parse(contenu_module)
        definis = {
            n.name for n in ast.walk(arbre)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        definis |= {
            cible.id for n in ast.walk(arbre) if isinstance(n, ast.Assign)
            for cible in n.targets if isinstance(cible, ast.Name)
        }
        for nom in [n.strip() for n in noms_bruts.replace("\n", "").split(",") if n.strip()]:
            if nom not in definis:
                manquants.append(f"{module}.{nom} importé dans app.py mais introuvable dans {module}.py")
    assert not manquants, f"{manquants}"



print("=== DIAGNOSTIC EXAMENSCAM ===\n")
tester("database_corriges.py", test_database_corriges)
tester("database_blanches.py", test_database_blanches)
tester("database_carrefour.py", test_database_carrefour)
tester("database_externes.py", test_database_externes)
tester("parser_titre_sujetexa.py (+ bug région corrigé)", test_parser_titre)
tester("Tables SQLite (5 attendues)", test_tables_existent)
tester("Templates HTML (7 attendus)", test_templates_existent)
tester("CSS nouvelles_pages.css", test_css_existe)
tester("app.py — routes dupliquées", test_routes_dupliquees)
tester("app.py — fonctions importées absentes du module", test_fonctions_importees_existent)
tester("app.py — colonne 'categorie' cohérente", test_categorie_colonne)
tester("app.py — montant paiement codé en dur (avertissement)", test_montant_paiement_coherent)
tester("app.py — imports Flask redondants", test_imports_flask_redondants)

print("\n=== RÉSUMÉ ===")
echecs = [r for r in resultats if not r[1]]
if echecs:
    print(f"❌ {len(echecs)} problème(s) à corriger avant de continuer :")
    for nom, ok, erreur in echecs:
        print(f" - {nom} : {erreur}")
else:
    print(f"✅ Tout est en place ({len(resultats)}/{len(resultats)}). Prêt pour les routes app.py.")
