"""
fix_niveau_premiere.py — ExamensCam
Corrige les 809 lignes de annales_externes importees avec
niveau='Premiere' (mapping errone de CORRESPONDANCE_NIVEAU_SERIE),
alors que le reste du site utilise 'Probatoire' partout.

Previsualise avant de modifier (regle du projet : jamais de
DELETE/UPDATE de masse sans confirmation).

Usage : python fix_niveau_premiere.py
"""
import sqlite3

conn = sqlite3.connect('data/annales.db')

avant = conn.execute("SELECT COUNT(*) FROM annales_externes WHERE niveau = 'Premiere'").fetchone()[0]
print(f"{avant} lignes avec niveau='Premiere' trouvees.")

if avant == 0:
    print("Rien a corriger.")
else:
    reponse = input(f"Renommer ces {avant} lignes en niveau='Probatoire' ? (oui/non) : ")
    if reponse.strip().lower() == 'oui':
        conn.execute("UPDATE annales_externes SET niveau = 'Probatoire' WHERE niveau = 'Premiere'")
        conn.commit()
        apres = conn.execute("SELECT COUNT(*) FROM annales_externes WHERE niveau = 'Probatoire'").fetchone()[0]
        print(f"Corrige. Total niveau='Probatoire' maintenant : {apres}")
    else:
        print("Annule.")

conn.close()