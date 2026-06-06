import sqlite3
c = sqlite3.connect('data/annales.db')

# Ajouter une contrainte unique pour éviter les doublons futurs
c.execute('''
    CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_annale 
    ON annales(niveau, serie, matiere, annee)
''')
c.commit()
print('Contrainte UNIQUE ajoutée.')
