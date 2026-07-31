# test_slug_probatoire2.py
from database_carrefour import get_carrefour
import json
print(json.dumps(get_carrefour("Probatoire", "Mathematiques", serie="C"), indent=2, ensure_ascii=False))