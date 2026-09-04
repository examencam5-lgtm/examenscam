"""
scripts/import_liens_externes.py — ExamensCam
Importe un CSV classifie 'externe' (issu de classifier_epreuves.py)
dans la table 'annales_externes'.

Dedoublonnage a deux niveaux :
  1. UNIQUE(lien_externe) -- meme lien PDF exact.
  2. signature_dedup -- meme devoir scrape sur DEUX sites differents
     (sujetexa ET epreuvesetcorriges), donc deux lien_externe
     differents mais le meme etablissement/matiere/annee/sequence.
     Verifie manuellement avant insert (pas de contrainte UNIQUE
     stricte dessus -- trop risque de rejeter de vrais doublons
     legitimes, voir migration_signature_dedup.py pour le detail).

Usage :
    python scripts/import_liens_externes.py data/liens_externes/a_indexer_externe.csv terminale-c

═══════════════════════════════════════════════════════
MIGRATION POSTGRES (NEON) — 04/09/2026
═══════════════════════════════════════════════════════
Même migration que les autres modules database_*.py, MAIS avec une
différence de fond importante, pas seulement de syntaxe :

⚠️ COMMIT PAR LIGNE, PAS UN SEUL COMMIT FINAL. L'original SQLite
n'exécutait qu'un conn.commit() à la toute fin de la boucle -- une
ligne en erreur (ex: doublon) n'empêchait pas les lignes suivantes de
s'insérer dans la même transaction. EN POSTGRES, CE N'EST PAS VRAI :
dès qu'une requête échoue, toute la transaction en cours passe en
état "avorté" et plus rien ne peut s'exécuter dessus tant qu'un
ROLLBACK explicite n'a pas été fait -- même les lignes suivantes,
pourtant valides, auraient échoué en cascade avec l'ancienne
structure. Corrigé en committant (ou en annulant) après CHAQUE ligne
traitée.

⚠️ DOUBLONS PAR LIEN EXACT VIA "ON CONFLICT ... DO NOTHING" : plutôt
que de déclencher une exception (psycopg2.errors.UniqueViolation) puis
la rattraper -- ce qui aurait aussi avorté la transaction en cours à
chaque doublon -- on utilise la clause native Postgres ON CONFLICT
(lien_externe) DO NOTHING RETURNING id. Si la ligne existe déjà,
aucune exception n'est levée, RETURNING ne renvoie simplement rien.

⚠️ SCHÉMA DE LA TABLE DÉDUIT, À VÉRIFIER : aucun CREATE TABLE pour
`annales_externes` n'a été fourni au moment de cette migration.
Le create_table() ci-dessous est une RECONSTITUTION basée sur les
colonnes utilisées dans ce fichier et dans database_externes.py.
Si l'ancien data/annales.db existe encore quelque part, vérifiez avec
`sqlite3 data/annales.db ".schema annales_externes"` et signalez
toute différence AVANT le premier import réel sur la nouvelle base.

CE QUI NE CHANGE PAS : la logique métier (dédoublonnage par
signature, détection niveau/série/matière, formats de CSV acceptés).
"""

import csv
import sys
import os
import re
from pathlib import Path

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generer_search_index import generer as regenerer_index
from migration_signature_dedup import calculer_signature
from extracteur_matiere import detecter_matiere

# On importe le parseur -- il doit etre dans le meme dossier scripts/
from parser_titre_sujetexa import parser_titre

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "(voir .env en local, ou Render en production) avant de lancer cet "
        "import -- sans elle, aucune ecriture n'est possible."
    )

CORRESPONDANCE_NIVEAU_SERIE = {
    "troisieme": ("BEPC", None),
    "premiere-a": ("Probatoire", "A"),
    "premiere-c": ("Probatoire", "C"),
    "premiere-d": ("Probatoire", "D"),
    "terminale-a": ("BAC", "A"),
    "terminale-c": ("BAC", "C"),
    "terminale-d": ("BAC", "D"),
}


def extraire_serie_depuis_classe(niveau: str, classe_detectee: str) -> str | None:
    """
    Deduit la serie (C, D, A4, TI...) depuis le code de classe
    detecte par le parseur (ex: 'TLeC' -> 'C', 'PA' -> 'A').
    Retourne None pour BEPC (pas de serie) ou si aucun code de
    classe n'a ete detecte dans le titre -- dans ce dernier cas,
    la ligne sera importee avec serie=NULL plutot que devinee a tort.

    INCHANGÉ par la migration -- logique Python pure, pas de SQL.
    """
    if niveau == "BEPC" or not classe_detectee:
        return None

    c = classe_detectee.upper()
    # Retire le prefixe Terminale (T, TLE, LE...) pour le BAC
    c = re.sub(r"^T?LE?", "", c)
    # Retire le prefixe Probatoire (P) -- uniquement si le reste
    # ressemble a un code serie valide, pour ne pas casser un code
    # qui commencerait deja par une lettre serie coincidant avec 'P'
    if niveau == "Probatoire" and c.startswith("P"):
        c = c[1:]
    c = c.strip()
    return c or None


def get_connection():
    """Retourne une connexion Postgres dont les curseurs renvoient des
    lignes de type dict (RealDictRow)."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def create_table():
    """⚠️ SCHÉMA DÉDUIT, PAS CONFIRMÉ -- voir avertissement en tête de
    fichier. Idempotent (CREATE TABLE IF NOT EXISTS), à appeler avant
    le premier import réel sur la nouvelle base."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS annales_externes (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                niveau TEXT NOT NULL,
                serie TEXT,
                matiere TEXT NOT NULL,
                annee INTEGER NOT NULL,
                titre TEXT,
                etablissement TEXT,
                region TEXT,
                sequence INTEGER,
                type_evaluation TEXT,
                classe_detectee TEXT,
                lien_externe TEXT NOT NULL UNIQUE,
                lien_page_source TEXT,
                source_site TEXT,
                signature_dedup TEXT,
                vues INTEGER DEFAULT 0,
                date_ajout TEXT DEFAULT (NOW()::text),
                actif INTEGER DEFAULT 1
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_externes_niveau_serie ON annales_externes(niveau, serie);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_externes_matiere ON annales_externes(matiere);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_externes_signature ON annales_externes(signature_dedup);")
        conn.commit()
    finally:
        conn.close()


def importer_csv(chemin_csv: str, niveau_serie: str = None):
    """
    Deux modes :
    - niveau_serie fourni (ex: 'terminale-c') : TOUTES les lignes du
      CSV recoivent ce niveau/serie -- adapte a sujetexa, dont un
      fichier scrape correspond deja a UN SEUL niveau/serie.
    - niveau_serie absent : chaque ligne deduit son propre
      niveau/serie depuis 'niveau_devine' (colonne CSV) + le code de
      classe detecte dans le titre -- adapte a epreuvesetcorriges,
      dont un seul fichier melange tous les niveaux/series.

    MIGRATION : commit (ou rollback) après CHAQUE ligne traitée --
    voir avertissement en tête de fichier sur l'abandon de transaction
    Postgres. Les doublons par lien exact ne lèvent plus d'exception
    (ON CONFLICT ... DO NOTHING), seuls les VRAIS imprévus (erreurs de
    type, colonnes manquantes, etc.) déclenchent le bloc except.
    """
    mode_uniforme = niveau_serie is not None

    if mode_uniforme:
        if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
            print(f"niveau_serie inconnu : {niveau_serie}")
            print(f"Options : {list(CORRESPONDANCE_NIVEAU_SERIE.keys())}")
            return
        niveau_fixe, serie_fixe = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]

    chemin = Path(chemin_csv)
    if not chemin.exists():
        print(f"Fichier introuvable : {chemin_csv}")
        return

    conn = get_connection()
    inseres = 0
    ignores_sans_pdf = 0
    ignores_sans_annee = 0
    ignores_sans_matiere = 0
    ignores_sans_niveau_serie = 0
    doublons_lien = 0
    doublons_signature = 0
    erreurs = 0

    try:
        with open(chemin, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for ligne in reader:
                lien_pdf = (ligne.get("lien_pdf") or ligne.get("lien_externe") or "").strip()
                if not lien_pdf:
                    ignores_sans_pdf += 1
                    continue

                titre = ligne.get("titre", "")
                infos = parser_titre(titre)
                annee = ligne.get("annee") or ligne.get("annee_devinee") or infos["annee_detectee"]

                if not annee or not (1990 <= int(annee) <= 2030):
                    ignores_sans_annee += 1
                    print(f"Ignoree (annee invalide/absente) : '{titre[:60]}...'")
                    continue

                annee = int(annee)

                # Matiere : utilise la colonne CSV si presente et non-vide
                # (cas sujetexa, ou la sous-categorie EST la matiere),
                # sinon la deduit du titre (cas epreuvesetcorriges, qui
                # n'expose pas la matiere comme colonne separee)
                matiere = (ligne.get("matiere") or "").strip()
                if not matiere:
                    matiere = detecter_matiere(titre)
                if not matiere:
                    ignores_sans_matiere += 1
                    print(f"Ignoree (matiere indetectable) : '{titre[:60]}...'")
                    continue

                # Niveau/serie : fixe (mode uniforme) ou deduit ligne par
                # ligne (mode auto-detection, epreuvesetcorriges)
                if mode_uniforme:
                    niveau, serie = niveau_fixe, serie_fixe
                else:
                    niveau = (ligne.get("niveau_devine") or "").strip()
                    if niveau not in ("BAC", "Probatoire", "BEPC"):
                        ignores_sans_niveau_serie += 1
                        print(f"Ignoree (niveau non reconnu '{niveau}') : '{titre[:60]}...'")
                        continue
                    serie = extraire_serie_depuis_classe(niveau, infos["classe_detectee"])
                    # Pas de serie detectee pour un niveau qui en a besoin
                    # (BAC/Probatoire) -- on importe quand meme avec
                    # serie=NULL plutot que de rejeter.

                try:
                    # Dedup cross-sites : verifie si une ligne avec la
                    # meme signature existe deja (meme devoir vu sur un
                    # autre site). UNIQUEMENT si la sequence est connue
                    # -- voir raisonnement complet dans le commentaire
                    # d'origine, inchangé par la migration.
                    if infos["sequence"] is not None:
                        signature = calculer_signature(
                            niveau, serie, matiere, annee,
                            infos["etablissement"], infos["sequence"]
                        )
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT id FROM annales_externes WHERE signature_dedup = %s",
                            (signature,)
                        )
                        existe_deja = cur.fetchone()
                        if existe_deja:
                            doublons_signature += 1
                            continue
                    else:
                        signature = None

                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO annales_externes (
                            niveau, serie, matiere, annee, titre,
                            etablissement, region,
                            sequence, type_evaluation, classe_detectee,
                            lien_externe, lien_page_source, source_site,
                            signature_dedup
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (lien_externe) DO NOTHING
                        RETURNING id
                    """, (
                        niveau, serie,
                        matiere,
                        annee,
                        titre,
                        infos["etablissement"],
                        infos["region"],
                        infos["sequence"],
                        infos["type_evaluation"],
                        infos["classe_detectee"],
                        lien_pdf,
                        ligne.get("lien_page") or ligne.get("lien_page_source", ""),
                        ligne.get("source_site", "sujetexa"),
                        signature,
                    ))
                    resultat = cur.fetchone()
                    conn.commit()
                    if resultat:
                        inseres += 1
                    else:
                        doublons_lien += 1
                except (psycopg2.Error, ValueError) as e:
                    conn.rollback()
                    print(f"Erreur sur '{titre[:50]}...' : {e}")
                    erreurs += 1
    finally:
        conn.close()

    print(f"\nImport termine pour {chemin.name}")
    print(f"  Inserees : {inseres}")
    print(f"  Ignorees (pas de lien PDF) : {ignores_sans_pdf}")
    print(f"  Ignorees (annee invalide/absente) : {ignores_sans_annee}")
    print(f"  Ignorees (matiere indetectable) : {ignores_sans_matiere}")
    print(f"  Ignorees (niveau non reconnu) : {ignores_sans_niveau_serie}")
    print(f"  Doublons (meme lien exact) : {doublons_lien}")
    print(f"  Doublons (meme devoir, autre site) : {doublons_signature}")
    print(f"  Erreurs : {erreurs}")

    if inseres > 0:
        print("\nRegeneration de l'index de recherche...")
        regenerer_index()
    else:
        print("\nIndex non regenere (aucune nouvelle ligne importee).")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print("Usage :")
        print("  python import_liens_externes.py <chemin_csv> <niveau-serie>   # mode uniforme (sujetexa)")
        print("  python import_liens_externes.py <chemin_csv>                 # mode auto-detection (epreuvesetcorriges)")
        sys.exit(1)

    # NOUVEAU : s'assure que la table existe avant le premier import
    # sur la nouvelle base -- idempotent, sans effet si déjà créée.
    create_table()

    chemin = sys.argv[1]
    niveau_serie_arg = sys.argv[2] if len(sys.argv) == 3 else None
    importer_csv(chemin, niveau_serie_arg)