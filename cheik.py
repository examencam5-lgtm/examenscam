import sqlite3
c = sqlite3.connect('data/annales.db')

result = c.execute('''
    DELETE FROM annales 
    WHERE niveau='BAC' AND serie='D' AND matiere='Mathematiques'
''')
c.commit()
print(f'Supprimées : {result.rowcount}')
