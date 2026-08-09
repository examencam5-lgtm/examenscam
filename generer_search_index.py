"""
generer_search_index.py — ExamensCam
Regenere la table 'search_index' a partir des tables metier
(annales, annales_externes).

A relancer apres chaque import :
    python generer_search_index.py
    git add data/annales.db
    git commit -m "..."
    git push

Colonnes niveau/matiere/serie ajoutees en plus de libelle/destination :
necessaires au systeme de scoring (database_search.py) qui applique
des bonus de pertinence selon niveau/serie/matiere de chaque resultat.
"""
import sqlite3
import unicodedata
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'


def normaliser(texte: str) -> str:
    """
    'LYCÉE Classique d'Édéa' -> 'lycee classique d edea'
    Retire les accents, met en minuscules, remplace la ponctuation
    par des espaces. Necessaire pour que taper 'lycee' sans accent
    trouve 'LYCÉE'.
    """
    if not texte:
        return ""
    texte = texte.lower()
    texte = unicodedata.normalize('NFKD', texte)
    texte = ''.join(c for c in texte if not unicodedata.combining(c))
    for char in "'’-_.,":
        texte = texte.replace(char, ' ')
    return ' '.join(texte.split())


def creer_table_index(conn):
    conn.executescript("""
        DROP TABLE IF EXISTS search_index;
        CREATE TABLE search_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            libelle TEXT NOT NULL,
            libelle_recherche TEXT NOT NULL,
            destination TEXT NOT NULL,
            type_source TEXT NOT NULL,
            niveau TEXT,
            matiere TEXT,
            serie TEXT
        );
        CREATE INDEX idx_search_libelle ON search_index(libelle_recherche);
        CREATE INDEX idx_search_niveau ON search_index(niveau);
        CREATE INDEX idx_search_matiere ON search_index(matiere);
        CREATE INDEX idx_search_serie ON search_index(serie);
    """)


def peupler_officielles(conn):
    """
    Table 'annales' -> ex: 'BAC C Mathematiques 2023'
    Pas de page individuelle par annale -- le PDF s'affiche en
    accordeon inline dans la page de liste (annales.html, ancre
    #card-<annee>).
    """
    rows = conn.execute("""
        SELECT id, niveau, serie, matiere, annee, type_sujet
        FROM annales WHERE actif = 1
    """).fetchall()

    entrees = []
    for r in rows:
        parties = [r['niveau']]
        if r['serie']:
            parties.append(r['serie'])
        parties.append(r['matiere'])
        parties.append(str(r['annee']))
        libelle = ' '.join(parties)

        if r['serie']:
            destination = f"/annales/{r['niveau']}/{r['serie']}/{r['matiere']}/enonces#card-{r['annee']}"
        else:
            destination = f"/annales/{r['niveau']}/{r['matiere']}/enonces#card-{r['annee']}"

        entrees.append((libelle, normaliser(libelle), destination, 'officiel', r['niveau'], r['matiere'], r['serie']))

    conn.executemany(
        "INSERT INTO search_index (libelle, libelle_recherche, destination, type_source, niveau, matiere, serie) VALUES (?,?,?,?,?,?,?)",
        entrees
    )
    return len(entrees)


def peupler_externes(conn):
    """Table 'annales_externes' -> redirection vers la page article (jamais le PDF direct)."""
    rows = conn.execute("""
        SELECT id, niveau, serie, etablissement, matiere, sequence, region, annee, titre
        FROM annales_externes WHERE actif = 1
    """).fetchall()

    entrees = []
    for r in rows:
        if r['etablissement']:
            libelle = r['etablissement'].title()
        elif r['titre']:
            libelle = r['titre']
        else:
            libelle = r['matiere']

        libelle += f" - {r['matiere']}"
        if r['sequence']:
            libelle += f" - Sequence {r['sequence']}"
        if r['region']:
            libelle += f" ({r['region']})"

        entrees.append((libelle, normaliser(libelle), f"/redirection/{r['id']}", 'externe', r['niveau'], r['matiere'], r['serie']))

    conn.executemany(
        "INSERT INTO search_index (libelle, libelle_recherche, destination, type_source, niveau, matiere, serie) VALUES (?,?,?,?,?,?,?)",
        entrees
    )
    return len(entrees)


def generer():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        creer_table_index(conn)
        n1 = peupler_officielles(conn)
        n3 = peupler_externes(conn)
        conn.commit()

        print(f"Index regenere :")
        print(f"  - officielles : {n1}")
        print(f"  - externes    : {n3}")
        print(f"  - total       : {n1 + n3}")
    except Exception as e:
        print(f"Erreur generation index : {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == '__main__':
    generer()