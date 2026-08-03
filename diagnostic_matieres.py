import sqlite3

conn = sqlite3.connect('data/annales.db')

print("--- Matieres distinctes par table (avec repr() pour voir les accents/espaces exacts) ---")
for table in ("annales", "annales_blanches", "annales_externes"):
    print(f"\n{table} :")
    for row in conn.execute(f"SELECT DISTINCT matiere, COUNT(*) as n FROM {table} GROUP BY matiere ORDER BY matiere"):
        print(f"  {row[0]!r:35s} -> {row[1]}")

conn.close()