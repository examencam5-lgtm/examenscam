# test_slug_probatoire.py
from database_carrefour import get_slug_etablissements, get_carrefour
import json

print("Slug pour Probatoire C :", get_slug_etablissements("Probatoire", "C"))
print()
print("Carrefour complet Probatoire C Maths :")
print(json.dumps(get_carrefour("Probatoire", "Mathematiques", serie="C"), indent=2, ensure_ascii=False))