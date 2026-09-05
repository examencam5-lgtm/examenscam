"""
generer_search_index.py — ExamensCam
Regenere la table 'search_index' a partir des tables metier
(annales, annales_externes).

═══════════════════════════════════════════════════════
MIGRATION POSTGRES (NEON) + COLONNE ANNEE — 05/09/2026
═══════════════════════════════════════════════════════

CE QUI CHANGE :
  - sqlite3.connect(DB_PATH)  -> psycopg2.connect(DATABASE_URL)
  - conn.row_factory          -> cursor_factory=RealDictCursor
  - placeholders '?'          -> placeholders '%s'
  - AUTOINCREMENT             -> GENERATED ALWAYS AS IDENTITY
  - conn.executescript(...)   -> plusieurs cur.execute(...) séparés
    (psycopg2 n'a pas d'équivalent direct à executescript)
  - ⚠️ CORRECTIF : l'ancienne requête sur `annales` sélectionnait
    `type_sujet`, colonne qui n'existe PAS dans le schéma Postgres de
    `annales` (voir avertissement dans database.py) -- supprimée ici,
    elle n'était de toute façon jamais utilisée dans la boucle.
  - NOUVEAU : colonne `annee` ajoutée à `search_index`, indexée.
    Nécessaire pour que chat_parcourir.py puisse filtrer par année
    (4e étape de la navigation "Parcourir") sans reparser `libelle`.

CE QUI CHANGE DANS LA PROCÉDURE D'UTILISATION (important) :
  L'ancien flux "lancer le script en local -> git commit data/annales.db
  -> git push" n'a plus de sens : Postgres/Neon est une base serveur
  partagée, pas un fichier à committer. Ce script doit maintenant être
  exécuté DIRECTEMENT CONTRE LA BASE DE PRODUCTION (DATABASE_URL pointe
  déjà sur Neon). Render gratuit ne donnant pas d'accès shell, la
  route /admin/regenerer-index (voir app.py) permet de le déclencher
  depuis un navigateur/curl, protégée comme les autres routes admin.
  generer() retourne maintenant un dict structuré (au lieu de simples
  print) pour que cette route puisse répondre en JSON.
"""
import os
import unicodedata

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "sur Render avec la chaine de connexion Postgres fournie par Neon "
        "-- sans elle, l'index de recherche ne peut pas être régénéré."
    )


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def normaliser(texte: str) -> str:
    """
    'LYCÉE Classique d'Édéa' -> 'lycee classique d edea'
    Retire les accents, met en minuscules, remplace la ponctuation
    par des espaces. Necessaire pour que taper 'lycee' sans accent
    trouve 'LYCÉE'. Inchangé par rapport à l'original -- logique pure
    Python, aucun lien avec sqlite/psycopg2.
    """
    if not texte:
        return ""
    texte = texte.lower()
    texte = unicodedata.normalize('NFKD', texte)
    texte = ''.join(c for c in texte if not unicodedata.combining(c))
    for char in "'’-_.,":
        texte = texte.replace(char, ' ')
    return ' '.join(texte.split())


def creer_table_index(cur):
    cur.execute("DROP TABLE IF EXISTS search_index;")
    cur.execute("""
        CREATE TABLE search_index (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            libelle TEXT NOT NULL,
            libelle_recherche TEXT NOT NULL,
            destination TEXT NOT NULL,
            type_source TEXT NOT NULL,
            niveau TEXT,
            matiere TEXT,
            serie TEXT,
            annee INTEGER
        );
    """)
    cur.execute("CREATE INDEX idx_search_libelle ON search_index(libelle_recherche);")
    cur.execute("CREATE INDEX idx_search_niveau ON search_index(niveau);")
    cur.execute("CREATE INDEX idx_search_matiere ON search_index(matiere);")
    cur.execute("CREATE INDEX idx_search_serie ON search_index(serie);")
    cur.execute("CREATE INDEX idx_search_annee ON search_index(annee);")


def peupler_officielles(cur):
    """
    Table 'annales' -> ex: 'BAC C Mathematiques 2023'
    Pas de page individuelle par annale -- le PDF s'affiche en
    accordeon inline dans la page de liste (annales.html, ancre
    #card-<annee>). Inchangé par rapport à l'original.
    """
    cur.execute("""
        SELECT id, niveau, serie, matiere, annee
        FROM annales WHERE actif = 1
    """)
    rows = cur.fetchall()

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

        entrees.append((libelle, normaliser(libelle), destination, 'officiel',
                         r['niveau'], r['matiere'], r['serie'], r['annee']))

    if entrees:
        cur.executemany(
            """INSERT INTO search_index
               (libelle, libelle_recherche, destination, type_source, niveau, matiere, serie, annee)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            entrees
        )
    return len(entrees)


def peupler_externes(cur):
    """Table 'annales_externes' -> redirection vers la page article
    (jamais le PDF direct) via /redirection/<id>, qui journalise la
    vue avant de rediriger. Inchangé par rapport à l'original."""
    cur.execute("""
        SELECT id, niveau, serie, etablissement, matiere, sequence, region, annee, titre
        FROM annales_externes WHERE actif = 1
    """)
    rows = cur.fetchall()

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

        entrees.append((libelle, normaliser(libelle), f"/redirection/{r['id']}", 'externe',
                         r['niveau'], r['matiere'], r['serie'], r['annee']))

    if entrees:
        cur.executemany(
            """INSERT INTO search_index
               (libelle, libelle_recherche, destination, type_source, niveau, matiere, serie, annee)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            entrees
        )
    return len(entrees)


def generer() -> dict:
    """Retourne {'ok': bool, 'officielles': int, 'externes': int,
    'total': int, 'erreur': str|None} -- utilisé à la fois en CLI
    (voir __main__) et depuis la route /admin/regenerer-index."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        creer_table_index(cur)
        n1 = peupler_officielles(cur)
        n3 = peupler_externes(cur)
        conn.commit()
        return {'ok': True, 'officielles': n1, 'externes': n3, 'total': n1 + n3, 'erreur': None}
    except Exception as e:
        conn.rollback()
        return {'ok': False, 'officielles': 0, 'externes': 0, 'total': 0, 'erreur': str(e)}
    finally:
        conn.close()


if __name__ == '__main__':
    resultat = generer()
    if resultat['ok']:
        print("Index regenere :")
        print(f"  - officielles : {resultat['officielles']}")
        print(f"  - externes    : {resultat['externes']}")
        print(f"  - total       : {resultat['total']}")
    else:
        print(f"Erreur generation index : {resultat['erreur']}")