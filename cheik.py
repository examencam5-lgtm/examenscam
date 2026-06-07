import sqlite3
c = sqlite3.connect('data/annales.db')

# Ajouter la colonne type_sujet
try:
    c.execute("ALTER TABLE annales ADD COLUMN type_sujet TEXT DEFAULT 'officiel'")
    c.commit()
    print('Colonne type_sujet ajoutée.')
except Exception as e:
    print(f'Erreur : {e}')

# Vérifier
cols = c.execute("PRAGMA table_info(annales)").fetchall()
for col in cols:
    print(col[1], col[2])
