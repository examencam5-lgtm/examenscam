"""
generer_search_index.py — ExamensCam
Regenere la table 'search_index' a partir des 3 tables metier
(annales, annales_blanches, annales_externes).

A relancer apres chaque import (CSV officiel, ajout blanche, scraping
externe) -- meme logique que ton workflow actuel :
    python generer_search_index.py
    git add data/annales.db
    git commit -m "..."
    git push

Pourquoi une table materialisee plutot qu'une VIEW SQL :
    L'autocompletion a besoin d'un LIKE rapide sur une colonne
    normalisee (sans accents/majuscules). Une VIEW recalculerait
    cette normalisation a chaque requete -- trop lent en usage reel.
    Ici on la calcule une fois, a l'import, en Python.
"""
import sqlite3
import unicodedata
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'


def normaliser(texte: str) -> str:
    """
    'LYCÉE Classique d'Édéa' -> 'lycee classique d edea'
    Retire les accents (NFKD + filtre des caracteres combinants),
    met en minuscules, remplace la ponctuation par des espaces.
    Necessaire pour que taper 'lycee' sans accent trouve 'LYCÉE'.
    """
    if not texte:
        return ""
    texte = texte.lower()
    texte = unicodedata.normalize('NFKD', texte)
    texte = ''.join(c for c in texte if not unicodedata.combining(c))
    # ponctuation -> espace, pour eviter de coller deux mots
    for char in "'’-_.,":
        texte = texte.replace(char, ' ')
    return ' '.join(texte.split())  # normalise les espaces multiples


def creer_table_index(conn):
    conn.executescript("""
        DROP TABLE IF EXISTS search_index;
        CREATE TABLE search_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            libelle TEXT NOT NULL,
            libelle_recherche TEXT NOT NULL,
            destination TEXT NOT NULL,
            type_source TEXT NOT NULL
        );
        CREATE INDEX idx_search_libelle ON search_index(libelle_recherche);
    """)


def peupler_officielles(conn):
    """
    Table 'annales' -> ex: 'BAC C Mathematiques 2023'
    IMPORTANT : il n'existe pas de page individuelle par annale --
    le PDF s'affiche en accordeon inline dans la page de liste
    (annales.html, voir #card-<annee>). La destination est donc la
    page de liste, avec une ancre sur l'annee pour que le clic ouvre
    directement le bon accordeon (JS a ajouter cote template : lire
    location.hash au chargement et appeler toggleAnnale()).

    Routes reelles (confirmees dans app.py) :
      BEPC/Probatoire : /annales/<niveau>/<type_sujet>/<matiere>
      BAC             : /annales/bac/<serie>/<type_sujet>/<matiere>
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

        # Routes reelles confirmees dans app.py :
        #   sans serie (BEPC) : /annales/<niveau>/<matiere>/enonces
        #   avec serie (BAC, Probatoire) : /annales/<niveau>/<serie>/<matiere>/enonces
        # 'enonces' choisi par defaut (pas 'corriges') -- c'est ce que
        # cherche l'immense majorite des recherches d'annales.
        if r['serie']:
            destination = f"/annales/{r['niveau']}/{r['serie']}/{r['matiere']}/enonces#card-{r['annee']}"
        else:
            destination = f"/annales/{r['niveau']}/{r['matiere']}/enonces#card-{r['annee']}"

        entrees.append((libelle, normaliser(libelle), destination, 'officiel'))

    conn.executemany(
        "INSERT INTO search_index (libelle, libelle_recherche, destination, type_source) VALUES (?,?,?,?)",
        entrees
    )
    return len(entrees)


def peupler_blanches(conn):
    """
    Table 'annales_blanches' -> ex: 'BAC C Mathematiques 2026 - Bac blanc (Ouest)'
    Meme logique que peupler_officielles : pas de page individuelle,
    on pointe vers la page de liste /blancs/<niveau>/<serie>/<matiere>.
    serie utilise 'na' quand NULL (cf. blancs_liste() dans app.py qui
    fait serie_reelle = None if serie == 'na' else serie).
    """
    rows = conn.execute("""
        SELECT id, niveau, serie, matiere, annee, region, type_evaluation, titre
        FROM annales_blanches WHERE actif = 1
    """).fetchall()

    entrees = []
    for r in rows:
        parties = [r['niveau']]
        if r['serie']:
            parties.append(r['serie'])
        parties.append(r['matiere'])
        parties.append(str(r['annee']))
        libelle = ' '.join(parties)
        if r['type_evaluation']:
            libelle += f" - {r['type_evaluation']}"
        if r['region']:
            libelle += f" ({r['region']})"

        serie_url = r['serie'] if r['serie'] else 'na'
        destination = f"/blancs/{r['niveau']}/{serie_url}/{r['matiere']}"

        entrees.append((libelle, normaliser(libelle), destination, 'blanc'))

    conn.executemany(
        "INSERT INTO search_index (libelle, libelle_recherche, destination, type_source) VALUES (?,?,?,?)",
        entrees
    )
    return len(entrees)


def peupler_externes(conn):
    """
    Table 'annales_externes' -> ex: 'Lycee Classique d'Edea - Sequence 4 - Mathematiques'
    Se lit naturellement comme un contenu d'etablissement (doc section 3.4) --
    pas besoin de badge, le libelle suffit a distinguer.
    """
    rows = conn.execute("""
        SELECT id, etablissement, matiere, sequence, region, annee, titre
        FROM annales_externes WHERE actif = 1
    """).fetchall()

    entrees = []
    for r in rows:
        if r['etablissement']:
            libelle = r['etablissement'].title()
        elif r['titre']:
            libelle = r['titre']
        else:
            libelle = r['matiere']  # filet de securite, cas rare

        libelle += f" - {r['matiere']}"
        if r['sequence']:
            libelle += f" - Sequence {r['sequence']}"
        if r['region']:
            libelle += f" ({r['region']})"

        entrees.append((libelle, normaliser(libelle), f"/redirection/{r['id']}", 'externe'))

    conn.executemany(
        "INSERT INTO search_index (libelle, libelle_recherche, destination, type_source) VALUES (?,?,?,?)",
        entrees
    )
    return len(entrees)


def generer():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        creer_table_index(conn)
        n1 = peupler_officielles(conn)
        n2 = peupler_blanches(conn)
        n3 = peupler_externes(conn)
        conn.commit()

        print(f"Index regenere :")
        print(f"  - officielles : {n1}")
        print(f"  - blanches    : {n2}")
        print(f"  - externes    : {n3}")
        print(f"  - total       : {n1 + n2 + n3}")
    except Exception as e:
        print(f"Erreur generation index : {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == '__main__':
    generer()