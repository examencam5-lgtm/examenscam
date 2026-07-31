# test_diagnostic_etablissements.py
from database_carrefour import get_slug_etablissements, get_carrefour
from database_externes import CORRESPONDANCE_NIVEAU_SERIE
import json

cas = [
    ("BAC", "A4", "Philosophie"),
    ("BAC", "D", "Chimie"),
    ("BAC", "D", "Informatique"),
    ("BAC", "D", "Mathematiques"),
    ("BAC", "D", "SVT"),
    ("Probatoire", "A4", "Philosophie"),
]

for niveau, serie, matiere in cas:
    slug = get_slug_etablissements(niveau, serie)
    print(f"\n{niveau} {serie} {matiere}")
    print(f"  slug = {slug}")
    if slug and slug in CORRESPONDANCE_NIVEAU_SERIE:
        niveau_reel, serie_reel = CORRESPONDANCE_NIVEAU_SERIE[slug]
        print(f"  → correspond à niveau_reel='{niveau_reel}' serie_reel='{serie_reel}'")
    data = get_carrefour(niveau, matiere, serie=serie)
    print(f"  etablissements_enonces = {data['etablissements_enonces']}")