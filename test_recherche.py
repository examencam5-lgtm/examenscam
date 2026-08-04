"""
test_recherche.py — Test des alias et de la recherche enrichie
Lancer avec : python test_recherche.py
"""

from database_search import normaliser_avec_alias, rechercher_avec_alias, rechercher

# ═══════════════════════════════════════════════════════
# 1. TEST DES ALIAS
# ═══════════════════════════════════════════════════════

print("=" * 60)
print("🧪 TEST 1 : NORMALISATION AVEC ALIAS")
print("=" * 60)

tests_alias = [
    ("math", "Mathématiques"),
    ("math probat", "Mathématiques Probatoire"),
    ("phys chim svt bac c", "Physique Chimie SVT BAC C"),
    ("3eme maths 2024", "BEPC Mathématiques 2024"),
    ("philo term c", "Philosophie BAC C"),
    ("angl prob d", "Anglais Probatoire D"),
    ("svt bepc", "SVT BEPC"),
    ("pc", "Physique-Chimie"),
    ("mathematiques", "Mathématiques"),
]

print("\n📝 Tests de normalisation :")
for saisie, attendu in tests_alias:
    resultat = normaliser_avec_alias(saisie)
    ok = "✅" if resultat == attendu else "❌"
    print(f"  {ok} '{saisie}' → '{resultat}' (attendu: '{attendu}')")

# ═══════════════════════════════════════════════════════
# 2. TEST DE COMPARAISON AVEC L'ANCIENNE RECHERCHE
# ═══════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("🧪 TEST 2 : COMPARAISON ANCIENNE VS NOUVELLE RECHERCHE")
print("=" * 60)

requetes_test = ["math", "phys", "svt", "probat", "angl"]

for req in requetes_test:
    print(f"\n🔍 Recherche : '{req}'")
    
    # Ancienne recherche (sans alias)
    anciens = rechercher(req, limite=5)
    print(f"   🔴 Ancienne : {len(anciens)} résultat(s)")
    
    # Nouvelle recherche (avec alias)
    nouveaux = rechercher_avec_alias(req, limite=5)
    print(f"   🟢 Nouvelle : {len(nouveaux)} résultat(s)")
    
    # Afficher les premiers résultats
    if nouveaux:
        print("   📄 Premiers résultats trouvés :")
        for r in nouveaux[:3]:
            print(f"      - {r['libelle']}")
    else:
        print("   ⚠️ Aucun résultat trouvé")

# ═══════════════════════════════════════════════════════
# 3. TEST DE RECHERCHE DÉTAILLÉE
# ═══════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("🧪 TEST 3 : RECHERCHE DÉTAILLÉE AVEC ALIAS")
print("=" * 60)

print("\n🔍 Recherche : 'math 2023'")
resultats = rechercher_avec_alias("math 2023", limite=8)

if resultats:
    print(f"   ✅ {len(resultats)} résultat(s) trouvé(s)")
    print("\n   📄 Détails :")
    for i, r in enumerate(resultats, 1):
        print(f"   {i}. {r['libelle']}")
        print(f"      → {r['destination']}")
        print(f"      (source: {r['type_source']})")
        print()
else:
    print("   ⚠️ Aucun résultat trouvé")

# ═══════════════════════════════════════════════════════
# 4. RÉSUMÉ FINAL
# ═══════════════════════════════════════════════════════

print("=" * 60)
print("📊 RÉSUMÉ DU TEST")
print("=" * 60)

# Vérifier si les alias ont un effet
test_alias_ok = True
for saisie, attendu in tests_alias:
    if normaliser_avec_alias(saisie) != attendu:
        test_alias_ok = False
        break

test_recherche_ok = False
# Tester si "math" trouve plus de résultats avec les alias
nb_ancien = len(rechercher("math", limite=10))
nb_nouveau = len(rechercher_avec_alias("math", limite=10))

if nb_nouveau > nb_ancien:
    test_recherche_ok = True
    print("✅ Les alias améliorent les résultats de recherche !")
    print(f"   'math' : ancien={nb_ancien}, nouveau={nb_nouveau} (+{nb_nouveau - nb_ancien} résultats)")
elif nb_nouveau == nb_ancien and nb_nouveau > 0:
    print("ℹ️ Les alias fonctionnent mais n'ont pas changé le nombre de résultats")
    print(f"   'math' : {nb_nouveau} résultats trouvés")
else:
    print("⚠️ Les alias n'ont pas encore d'effet (peut-être pas de données avec 'Mathématiques')")
    print(f"   'math' : ancien={nb_ancien}, nouveau={nb_nouveau}")

print("\n" + "=" * 60)
print("🏁 FIN DES TESTS")
print("=" * 60)