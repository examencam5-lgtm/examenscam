"""
consolider_matieres_v3.py — ExamensCam
Corrige le vrai probleme : les lignes non-pertinentes avaient
serie=None, qui "fuit" sur TOUTES les series (C, D, TI, A4) a
cause du OR serie IS NULL dans les requetes d'affichage. Les
scripts precedents cherchaient serie IN ('C','D','TI') exact,
qui ne matchait jamais ces lignes -> 0 supprime a chaque fois.

Regle : on supprime CES matieres precises partout au BAC/Probatoire
SAUF quand elles sont explicitement rattachees a une serie A ou A4
(litteraire, ou elles sont legitimes).

Usage : python consolider_matieres_v3.py
"""
import sqlite3

conn = sqlite3.connect('data/annales.db')
TABLES = ("annales", "annales_blanches", "annales_externes")

SCIENCES_ECO = ["Sciences Économiques et Juridiques", "Sciences Économiques et de Gestion",
                "Sciences Economiques et Juridiques", "Sciences Economiques et de Gestion"]

# Matieres jamais pertinentes en serie scientifique -- supprimees
# partout SAUF si explicitement serie='A' ou 'A4' (litteraire)
NON_PERTINENT_SCIENTIFIQUE = ["Allemand", "Espagnol", "Culture Generale", "Travail Manuel"] + SCIENCES_ECO

total_supprime = 0

def supprimer(table, condition_sql, params, label):
    global total_supprime
    n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {condition_sql}", params).fetchone()[0]
    if n:
        conn.execute(f"DELETE FROM {table} WHERE {condition_sql}", params)
        print(f"  {table} : {label} -> {n} lignes supprimees")
        total_supprime += n

print("=== BEPC : Allemand, Espagnol (tous, pas de serie) ===")
for table in TABLES:
    for m in ["Allemand", "Espagnol"]:
        supprimer(table, "niveau = 'BEPC' AND matiere = ?", (m,), m)

print("\n=== BAC/Probatoire : LV2/Culture Generale/TM/Sciences Eco -- partout SAUF serie A/A4 ===")
for table in TABLES:
    for m in NON_PERTINENT_SCIENTIFIQUE:
        supprimer(
            table,
            "niveau IN ('BAC','Probatoire') AND matiere = ? AND (serie IS NULL OR serie NOT IN ('A','A4'))",
            (m,), m
        )

print("\n=== BAC/Probatoire serie A/A4 : pas de Physique/Chimie (litteraire) ===")
for table in TABLES:
    for m in ("Physique", "Chimie"):
        supprimer(
            table,
            "niveau IN ('BAC','Probatoire') AND serie IN ('A','A4') AND matiere = ?",
            (m,), m
        )

print("\n=== PCT interdit au BAC/Probatoire (deja separe en Physique+Chimie) ===")
for table in TABLES:
    supprimer(table, "niveau IN ('BAC','Probatoire') AND matiere = 'PCT'", (), "PCT")

conn.commit()
conn.close()

print(f"\nTotal supprime : {total_supprime} lignes")
print("Regenere l'index maintenant :")
print("  python generer_search_index.py")