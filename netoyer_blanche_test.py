"""
nettoyer_blanches_test.py — ExamensCam
Supprime les lignes de test (region='TEST') dans annales_blanches,
en gardant uniquement les vraies donnees.

Usage :
    python nettoyer_blanches_test.py
"""
import sqlite3
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'


def nettoyer():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Verification avant suppression -- toujours previsualiser avant
    # une operation destructive (regle etablie du projet)
    a_supprimer = conn.execute(
        "SELECT id, niveau, serie, matiere, annee FROM annales_blanches WHERE region = 'TEST'"
    ).fetchall()

    print(f"Lignes qui vont etre supprimees ({len(a_supprimer)}) :")
    for r in a_supprimer:
        print(f"  id={r['id']} | {r['niveau']} {r['serie']} {r['matiere']} {r['annee']}")

    if not a_supprimer:
        print("Rien a nettoyer.")
        conn.close()
        return

    reponse = input(f"\nConfirmer la suppression de ces {len(a_supprimer)} lignes ? (oui/non) : ")
    if reponse.strip().lower() != 'oui':
        print("Annule.")
        conn.close()
        return

    conn.execute("DELETE FROM annales_blanches WHERE region = 'TEST'")
    conn.commit()

    restant = conn.execute("SELECT COUNT(*) as n FROM annales_blanches").fetchone()['n']
    print(f"\nSupprime. Lignes restantes dans annales_blanches : {restant}")

    conn.close()


if __name__ == '__main__':
    nettoyer()