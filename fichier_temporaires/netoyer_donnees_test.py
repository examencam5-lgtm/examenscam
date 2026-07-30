# nettoyer_donnees_test.py
"""
Supprime TOUTES les données de test, peu importe le format de tag
utilisé (le nouveau 'TEST_TEMPORAIRE'/'[TEST]%' et l'ancien 'test'/
'Pack Corrigés Test%' des tout premiers essais).
Ne touche à AUCUNE vraie donnée -- filtre strict sur ces marqueurs connus.

À lancer juste avant de commencer le remplissage avec les vraies annales.

Usage : python nettoyer_donnees_test.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'

conn = sqlite3.connect(DB_PATH)

print("=== NETTOYAGE DONNÉES DE TEST (tous formats) ===\n")

# 1. annales (officiel) -- nouveau tag ET ancien tag minuscule
n1 = conn.execute("DELETE FROM annales WHERE source IN ('TEST_TEMPORAIRE', 'test')").rowcount
print(f"1. annales supprimées : {n1}")

# 2. annales_externes -- nouveau tag ET ancien tag minuscule
n2 = conn.execute("DELETE FROM annales_externes WHERE source_site IN ('TEST_TEMPORAIRE', 'test')").rowcount
print(f"2. annales_externes supprimées : {n2}")

# 3. annales_blanches -- titre préfixé [TEST] (un seul format utilisé depuis le début ici)
n3 = conn.execute("DELETE FROM annales_blanches WHERE titre LIKE '[TEST]%'").rowcount
print(f"3. annales_blanches supprimées : {n3}")

# 4. corriges_fichiers liés aux packs de test -- AVANT de supprimer les packs
#    (nouveau format [TEST]... ET ancien format "Pack Corrigés Test...")
n4 = conn.execute("""
    DELETE FROM corriges_fichiers
    WHERE pack_id IN (
        SELECT id FROM packs_corriges
        WHERE titre LIKE '[TEST]%' OR titre LIKE 'Pack Corrigés Test%'
    )
""").rowcount
print(f"4. corriges_fichiers supprimés : {n4}")

# 5. packs_corriges -- les deux formats de titre
n5 = conn.execute("""
    DELETE FROM packs_corriges
    WHERE titre LIKE '[TEST]%' OR titre LIKE 'Pack Corrigés Test%'
""").rowcount
print(f"5. packs_corriges supprimés : {n5}")

conn.commit()
conn.close()

print(f"\n=== TERMINÉ — {n1+n2+n3+n4+n5} lignes de test supprimées au total ===")
print("Vérifie avec verifier_tout.py que le site tourne toujours normalement.")
print("Vérifie aussi visuellement /carrefour/bac/C/Mathematiques -- il doit")
print("redevenir 'vide' (1 seule branche ou moins) puisque les données de test sont parties.")
print("Tu peux maintenant commencer l'import des vraies données en confiance.")