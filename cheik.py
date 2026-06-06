import sqlite3
c = sqlite3.connect('data/annales.db')
c.row_factory = sqlite3.Row

print('=== PROBATOIRE (5 premiers) ===')
rows = c.execute('SELECT id, niveau, serie, matiere, annee, actif FROM annales WHERE niveau = "Probatoire" LIMIT 5').fetchall()
for r in rows:
    print(dict(r))

print()
print('=== BAC serie NULL ===')
count = c.execute('SELECT COUNT(*) FROM annales WHERE niveau = "BAC" AND (serie IS NULL OR serie = "")').fetchone()[0]
print('BAC sans série:', count)

print()
print('=== BAC serie NULL - matières distinctes ===')
rows = c.execute('SELECT DISTINCT matiere FROM annales WHERE niveau = "BAC" AND (serie IS NULL OR serie = "")').fetchall()
for r in rows:
    print(r['matiere'])
