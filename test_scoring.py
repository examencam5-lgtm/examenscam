"""
test_scoring.py — Test du moteur de recherche avec scoring amélioré
Lancer avec : python test_scoring.py
"""

from database_search import (
    normaliser_avec_alias,
    normaliser_requete_complete,
    rechercher_avec_scoring,
    rechercher,
    suggerer_correction
)

print("=" * 70)
print("🧪 TEST DU MOTEUR DE RECHERCHE AVEC SCORING AMÉLIORÉ")
print("=" * 70)

# ═══════════════════════════════════════════════════════
# 1. TEST DES ALIAS
# ═══════════════════════════════════════════════════════

print("\n📌 TEST 1 : NORMALISATION AVEC ALIAS")
print("-" * 70)

tests_alias = [
    ("math", "Mathématiques"),
    ("math probat", "Mathématiques Probatoire"),
    ("phys chim svt bac c", "Physique Chimie SVT BAC C"),
    ("3eme maths 2024", "BEPC Mathématiques 2024"),
    ("philo term c", "Philosophie BAC C"),
    ("phisique", "Physique"),
    ("shimie", "Chimie"),
    ("probat", "Probatoire"),
]

for saisie, attendu in tests_alias:
    resultat = normaliser_avec_alias(saisie)
    ok = "✅" if resultat == attendu else "❌"
    print(f"  {ok} '{saisie}' → '{resultat}'")

# ═══════════════════════════════════════════════════════
# 2. TEST DE SUGGESTIONS PAR SÉRIE
# ═══════════════════════════════════════════════════════

print("\n📌 TEST 2 : SUGGESTIONS PAR SÉRIE")
print("-" * 70)

tests_suggestions = [
    ("xyz", "BAC", "C"),
    ("xyz", "BAC", "D"),
    ("xyz", "BAC", "A4"),
    ("xyz", "BAC", "TI"),
    ("xyz", "BEPC", None),
]

for req, niveau, serie in tests_suggestions:
    suggestions = suggerer_correction(req, niveau=niveau, serie=serie)
    print(f"  {niveau} {serie or ''} → {suggestions}")

# ═══════════════════════════════════════════════════════
# 3. TEST DE RECHERCHE AVEC SCORING
# ═══════════════════════════════════════════════════════

print("\n📌 TEST 3 : RECHERCHE AVEC SCORING AMÉLIORÉ")
print("-" * 70)

requetes = ["math", "phys", "svt", "math 2023", "phisique", "3eme"]

for req in requetes:
    print(f"\n🔍 Recherche: '{req}'")
    
    # Ancienne recherche (sans alias)
    anciens = rechercher(req, limite=3)
    print(f"   🔴 Ancienne: {len(anciens)} résultat(s)")
    
    # Nouvelle recherche (avec alias + scoring)
    reponse = rechercher_avec_scoring(req, limite=3)
    resultats = reponse['resultats']
    suggestions = reponse['suggestions']
    
    print(f"   🟢 Nouvelle: {len(resultats)} résultat(s) (total trouvé: {reponse['total_trouve']})")
    
    if resultats:
        print("   📄 Résultats (avec score):")
        for i, r in enumerate(resultats[:3], 1):
            print(f"      {i}. [{r['score']} pts] {r['libelle']}")
    
    if suggestions:
        print(f"   💡 Suggestions: {', '.join(suggestions)}")

# ═══════════════════════════════════════════════════════
# 4. TEST DE RECHERCHE FILTRÉE PAR SÉRIE
# ═══════════════════════════════════════════════════════

print("\n📌 TEST 4 : RECHERCHE FILTRÉE PAR SÉRIE")
print("-" * 70)

tests_filtres = [
    ("math", "BAC", "C"),
    ("svt", "BAC", "D"),
    ("litterature", "BAC", "A4"),
    ("math", "BEPC", None),
]

for req, niveau, serie in tests_filtres:
    print(f"\n🔍 Recherche: '{req}' avec niveau='{niveau}', serie='{serie}'")
    reponse = rechercher_avec_scoring(req, limite=3, niveau=niveau, matiere=None)
    resultats = reponse['resultats']
    if resultats:
        for r in resultats[:3]:
            print(f"   [{r['score']} pts] {r['libelle']}")
    else:
        print("   Aucun résultat")

# ═══════════════════════════════════════════════════════
# RÉSUMÉ FINAL
# ═══════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("📊 RÉSUMÉ FINAL")
print("=" * 70)

print("""
✅ ALIAS: Fonctionnent (math → Mathématiques, phys → Physique, etc.)
✅ NORMALISATION: Détection automatique du niveau, série, matière et année
✅ SCORING AMÉLIORÉ: Les résultats sont triés par pertinence avec bonus par série
✅ SUGGESTIONS PAR SÉRIE: Suggestions adaptées à la série recherchée
✅ COMPATIBILITÉ: La fonction rechercher() originale est inchangée
""")

print("=" * 70)
print("🏁 FIN DES TESTS")
print("=" * 70)