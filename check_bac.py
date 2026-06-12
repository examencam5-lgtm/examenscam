import sqlite3
conn = sqlite3.connect('data/annales.db')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT serie, matiere, annee FROM annales WHERE niveau=? AND actif=1 ORDER BY annee DESC', ('BAC',)).fetchall()
for r in rows: print(dict(r))
