"""
consolider_matieres_v2.py — ExamensCam
Nettoyage definitif des matieres hors-programme par niveau/serie.
Idempotent : relancer ce script ne pose aucun probleme, les lignes
deja supprimees ne matchent simplement plus rien la fois suivante.

Regles :
  BEPC                    : retire Allemand, Espagnol
  Probatoire/BAC C, D, TI : retire Allemand, Espagnol, Culture Generale,
                             Travail Manuel, Sciences Economiques (et Juridiques/de Gestion)
  Probatoire/BAC A4       : retire Chimie, Physique, Culture Generale,
                             Travail Manuel, Sciences Economiques (et Juridiques/de Gestion)

Usage : python consolider_matieres_v2.py
"""
import sqlite3

conn = sqlite3.connect('data/annales.db')
TABLES = ("annales", "annales_blanches", "annales_externes")

# Toutes les variantes de libelle possibles pour "sciences eco" --
# scrapees sous des noms legerement differents selon la source
SCIENCES_ECO = ["Sciences Économiques et Juridiques", "Sciences Économiques et de Gestion",
                "Sciences Economiques et Juridiques", "Sciences Economiques et de Gestion"]

NON_PERTINENT_SCIENTIFIQUE = ["Allemand", "Espagnol", "Culture Generale", "Travail Manuel"] + SCIENCES_ECO
NON_PERTINENT_A4 = ["Chimie", "Physique", "Culture Generale", "Travail Manuel"] + SCIENCES_ECO
NON_PERTINENT_BEPC = ["Allemand", "Espagnol"]

total_supprime = 0

def supprimer(table, condition_sql, params, label):
    global total_supprime
    n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {condition_sql}", params).fetchone()[0]
    if n:
        conn.execute(f"DELETE FROM {table} WHERE {condition_sql}", params)
        print(f"  {table} : {label} -> {n} lignes supprimees")
        total_supprime += n

print("=== BEPC : Allemand, Espagnol ===")
for table in TABLES:
    for m in NON_PERTINENT_BEPC:
        supprimer(table, "niveau = 'BEPC' AND matiere = ?", (m,), m)

print("\n=== Probatoire/BAC series C, D, TI : LV2, Culture Generale, TM, Sciences Eco ===")
for table in TABLES:
    for m in NON_PERTINENT_SCIENTIFIQUE:
        supprimer(table, "niveau IN ('BAC','Probatoire') AND serie IN ('C','D','TI') AND matiere = ?", (m,), m)

print("\n=== Probatoire/BAC serie A4 : Physique, Chimie, Culture Generale, TM, Sciences Eco ===")
for table in TABLES:
    for m in NON_PERTINENT_A4:
        supprimer(table, "niveau IN ('BAC','Probatoire') AND serie = 'A4' AND matiere = ?", (m,), m)

conn.commit()
conn.close()

print(f"\nTotal supprime : {total_supprime} lignes")
print("Regenere l'index maintenant :")
print("  python generer_search_index.py")