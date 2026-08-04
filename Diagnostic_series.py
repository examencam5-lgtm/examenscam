import sqlite3

conn = sqlite3.connect('data/annales.db')

print("--- Toutes les valeurs distinctes de 'serie' pour BAC et Probatoire (repr exact) ---")
for table in ("annales", "annales_blanches", "annales_externes"):
    rows = conn.execute(f"""
        SELECT DISTINCT niveau, serie FROM {table}
        WHERE niveau IN ('BAC', 'Probatoire')
        ORDER BY niveau, serie
    """).fetchall()
    print(f"\n{table} :")
    for r in rows:
        print(f"  niveau={r[0]!r} serie={r[1]!r}")

print("\n--- Lignes non-pertinentes trouvees, avec repr exact de serie/matiere ---")
cibles = ["Allemand", "Espagnol", "Culture Generale", "Travail Manuel", "Physique", "Chimie"]
for table in ("annales", "annales_blanches", "annales_externes"):
    print(f"\n{table} :")
    for m in cibles:
        rows = conn.execute(f"""
            SELECT niveau, serie, matiere, COUNT(*) as n
            FROM {table}
            WHERE niveau IN ('BAC', 'Probatoire') AND matiere = ?
            GROUP BY niveau, serie, matiere
        """, (m,)).fetchall()
        for r in rows:
            print(f"  niveau={r[0]!r} serie={r[1]!r} matiere={r[2]!r} -> {r[3]} lignes")

conn.close()