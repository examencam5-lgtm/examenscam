import csv
import sqlite3
import sys
from pathlib import Path

DB_PATH = 'data/annales.db'

def import_from_csv(csv_path):
    conn = sqlite3.connect(DB_PATH)
    count = 0
    ignores = 0

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                conn.execute('''
                    INSERT OR IGNORE INTO annales 
                    (niveau, serie, matiere, annee, lien_drive, 
                     corrige_dispo, source, type_sujet)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    row['niveau'],
                    row.get('serie') or None,
                    row['matiere'],
                    int(row['annee']),
                    row['lien_drive'],
                    int(row.get('corrige_dispo', 0)),
                    row.get('source', 'inconnu'),
                    row.get('type_sujet', 'officiel')
                ))
                if conn.execute('SELECT changes()').fetchone()[0]:
                    count += 1
                else:
                    ignores += 1
            except Exception as e:
                print(f'❌ Erreur : {e} — {row}')

    conn.commit()
    conn.close()
    print(f'✅ Importées : {count}')
    print(f'⏭️ Ignorées (doublons) : {ignores}')

if __name__ == '__main__':
    import_from_csv(sys.argv[1])
