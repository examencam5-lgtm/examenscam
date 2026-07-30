# injecter_donnees_test_global.py
"""
Injecte des données fictives sur plusieurs niveaux/séries/matières,
pour voir plusieurs carrefours différents s'afficher pendant que la
vraie collecte de données avance en parallèle.

Toutes les données créées ici sont marquées explicitement
(source='TEST_TEMPORAIRE' ou titre préfixé '[TEST]') pour être
supprimables à 100% sans risque via nettoyer_donnees_test.py.

Usage : python injecter_donnees_test_global.py
"""

import sqlite3
from pathlib import Path
from database import add_annale
from database_blanches import ajouter_epreuve_blanche

DB_PATH = Path('data') / 'annales.db'

# Combinaisons à peupler : (niveau, serie, matiere)
COMBINAISONS = [
    ("BEPC", None, "Mathematiques"),
    ("BEPC", None, "Français"),
    ("Probatoire", "C", "Mathematiques"),
    ("Probatoire", "A4", "Philosophie"),
    ("BAC", "C", "Mathematiques"),
    ("BAC", "D", "SVT"),
    ("BAC", "TI", "Informatique"),
    ("BAC", "A4", "Philosophie"),
]

TAG = "TEST_TEMPORAIRE"


def injecter_officiel(niveau, serie, matiere):
    nid = add_annale(
        niveau=niveau, serie=serie, matiere=matiere, annee=2024,
        lien_drive="https://drive.google.com/file/d/TEST_ID/preview",
        corrige_dispo=0, source=TAG
    )
    return nid


def injecter_pack_corriges(niveau, serie, matiere, categorie):
    conn = sqlite3.connect(DB_PATH)
    titre = f"[TEST] Pack Corrigés {categorie} {matiere} {niveau} {serie or ''}"
    if categorie == "officiel":
        annee_debut, annee_fin = 2020, 2024
    else:
        annee_debut, annee_fin = 2025, 2026
    try:
        conn.execute("""
            INSERT OR IGNORE INTO packs_corriges
                (niveau, serie, matiere, annee_debut, annee_fin, titre, prix, categorie, actif)
            VALUES (?, ?, ?, ?, ?, ?, 500, ?, 1)
        """, (niveau, serie, matiere, annee_debut, annee_fin, titre, categorie))
        conn.commit()
    except Exception as e:
        print(f"    ⚠️ pack {categorie} : {e}")
    finally:
        conn.close()

def injecter_blanc(niveau, serie, matiere):
    return ajouter_epreuve_blanche(
        niveau, matiere, 2026, "https://drive.google.com/test-blanc",
        serie=serie, region="TEST", type_evaluation="Test",
        titre=f"[TEST] Épreuve blanche {matiere} {niveau}"
    )

def injecter_etablissement(niveau, serie, matiere):
    conn = sqlite3.connect(DB_PATH)
    lien_unique = f"https://sujetexa.com/test-{niveau}-{serie or 'na'}-{matiere}.pdf"
    try:
        conn.execute("""
            INSERT OR IGNORE INTO annales_externes
                (niveau, serie, matiere, annee, titre, etablissement, region,
                 sequence, type_evaluation, classe_detectee, lien_externe,
                 lien_page_source, source_site, actif)
            VALUES (?, ?, ?, 2026, ?, 'COLLEGE TEST', 'TEST', 1, 'Test',
                    'TEST', ?, 'https://sujetexa.com/test-page', ?, 1)
        """, (niveau, serie, matiere, f"[TEST] {matiere} {niveau}", lien_unique, TAG))
        conn.commit()
    except Exception as e:
        print(f"    ⚠️ établissement : {e}")
    finally:
        conn.close()

print("=== INJECTION GLOBALE — DONNÉES DE TEST ===\n")
for niveau, serie, matiere in COMBINAISONS:
    print(f"→ {niveau} {serie or ''} {matiere}")
    injecter_officiel(niveau, serie, matiere)
    injecter_pack_corriges(niveau, serie, matiere, "officiel")
    injecter_blanc(niveau, serie, matiere)
    injecter_pack_corriges(niveau, serie, matiere, "blanc")
    injecter_etablissement(niveau, serie, matiere)

print("\n=== TERMINÉ ===")
print(f"{len(COMBINAISONS)} combinaisons peuplées avec des données marquées '{TAG}' / '[TEST]'.")
print("Navigue sur les différents carrefours pour voir plusieurs pages complètes.")
print("Quand tu commences les vraies données, lance nettoyer_donnees_test.py.")