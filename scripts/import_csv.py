import csv
import sqlite3
import sys
from pathlib import Path

# scripts/import_csv.py est dans un sous-dossier, mais
# generer_search_index.py est a la racine du projet -- on ajoute
# la racine au chemin de recherche Python pour que l'import marche
# peu importe d'ou le script est lance.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generer_search_index import generer as regenerer_index

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
                    (niveau, serie, matiere, annee, lien_drive, corrige_dispo, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    row['niveau'],
                    row.get('serie') or None,
                    row['matiere'],
                    int(row['annee']),
                    row['lien_drive'],
                    int(row.get('corrige_dispo', 0)),
                    row.get('source', 'inconnu')
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

    # Seulement si quelque chose a vraiment change -- inutile de
    # regenerer l'index si tout etait deja en base (0 import reel)
    if count > 0:
        print('\n🔄 Régénération de l\'index de recherche...')
        regenerer_index()
    else:
        print('\n⏭️  Index non régénéré (aucune nouvelle ligne importée).')

if __name__ == '__main__':
    import_from_csv(sys.argv[1])