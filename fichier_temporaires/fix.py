import sqlite3

conn = sqlite3.connect('data/annales.db')
result = conn.execute(
    "UPDATE annales SET serie='C' WHERE matiere='Chimie' AND serie IS NULL AND niveau='BAC'"
)
conn.commit()
print(f'{result.rowcount} lignes mises à jour')
conn.close()