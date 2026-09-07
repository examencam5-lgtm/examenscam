# database_progressions.py — ExamensCam
"""
Stocke les fiches de progression harmonisee nationale MINESEC (une par matiere
et par annee scolaire) et les evenements du calendrier scolaire, pour
interrogation par date. C'est la source de verite qui remplace toute
connaissance generique et potentiellement perimee que Gemini pourrait avoir
sur le programme et le calendrier camerounais.

Meme stack que database.py : Postgres gere chez Neon via DATABASE_URL,
psycopg2, RealDictCursor, placeholders %s, rollback() explicite sur erreur
d'ecriture (Postgres abandonne la transaction en cours des qu'une requete
echoue, contrairement a SQLite -- oublier le rollback() bloque tout appel
suivant sur la meme connexion).

Choix Postgres (et non un JSON charge en memoire) : Muhammad alimente ce
systeme matiere par matiere (Maths fait, Physique/Chimie/SVT a venir).
Postgres permet de croiser facilement (ex: "quelles matieres ont un chapitre
qui commence cette semaine en Tle C") sans reecrire un moteur de recherche
JSON a la main, et reste coherent avec le reste du projet deja migre.

CE QUI NE CHANGE PAS : les noms de fonctions et leurs signatures publiques,
pour rester appelables depuis chat_contexte.py sans adaptation si jamais tu
changes encore d'implementation plus tard.
"""

import json
import os
import re
from datetime import date, datetime
from typing import Optional

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "sur Render avec la chaine de connexion Postgres fournie par Neon "
        "-- sans elle, les progressions nationales ne peuvent ni etre lues "
        "ni ecrites."
    )

MOIS = {
    "jan": 1, "janv": 1, "fev": 2, "fév": 2, "fevr": 2, "mars": 3,
    "avr": 4, "avril": 4, "mai": 5, "juin": 6, "juil": 7,
    "aout": 8, "août": 8, "sept": 9, "oct": 10, "nov": 11, "dec": 12, "déc": 12,
}
MOIS_RE = "|".join(sorted(MOIS.keys(), key=len, reverse=True))


def get_connection():
    """Meme ergonomie que database.py : row['colonne'] et dict(row)
    fonctionnent directement grace a RealDictCursor."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def create_table():
    """Idempotent -- appelable au demarrage de app.py comme les autres
    create_table() du projet, jamais destructive sur une table existante."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS progressions_chapitres (
                id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                annee_scolaire  TEXT NOT NULL,
                matiere         TEXT NOT NULL,
                niveau          TEXT NOT NULL,
                serie           TEXT,
                ordre           INTEGER NOT NULL,
                nom_chapitre    TEXT NOT NULL,
                lecons          TEXT NOT NULL,      -- JSON liste de titres, stocke en texte
                semaine_texte   TEXT,
                date_debut      DATE,
                date_fin        DATE,
                evaluation      TEXT,
                UNIQUE(annee_scolaire, matiere, niveau, serie, ordre)
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS progressions_evenements (
                id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                annee_scolaire  TEXT NOT NULL,
                date_debut      DATE NOT NULL,
                date_fin        DATE,
                label           TEXT NOT NULL,
                UNIQUE(annee_scolaire, date_debut, label)
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_prog_matiere_niveau "
                    "ON progressions_chapitres(matiere, niveau, serie);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_prog_dates "
                    "ON progressions_chapitres(date_debut, date_fin);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_evenements_dates "
                    "ON progressions_evenements(date_debut, date_fin);")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"create_table (progressions) error: {e}")
    finally:
        conn.close()


def _parse_un_bloc_date(bloc: str):
    """Parse un bloc du type '07-11 sept 2026' ou '28 sept-02 oct 2026'
    ou '05 juin 2027'. Retourne (date_debut, date_fin) ou (None, None)."""
    bloc = bloc.strip()

    m = re.match(rf"(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})\s+({MOIS_RE})\.?\s+(\d{{4}})",
                 bloc, re.IGNORECASE)
    if m:
        j1, j2, mois_txt, annee = m.groups()
        try:
            return (date(int(annee), MOIS[mois_txt.lower()], int(j1)),
                    date(int(annee), MOIS[mois_txt.lower()], int(j2)))
        except ValueError:
            return None, None

    m = re.match(
        rf"(\d{{1,2}})\s+({MOIS_RE})\.?\s*[-–]\s*(\d{{1,2}})\s+({MOIS_RE})\.?\s+(\d{{4}})",
        bloc, re.IGNORECASE
    )
    if m:
        j1, mois1_txt, j2, mois2_txt, annee = m.groups()
        try:
            return (date(int(annee), MOIS[mois1_txt.lower()], int(j1)),
                    date(int(annee), MOIS[mois2_txt.lower()], int(j2)))
        except ValueError:
            return None, None

    m = re.match(rf"(\d{{1,2}})\s+({MOIS_RE})\.?\s+(\d{{4}})", bloc, re.IGNORECASE)
    if m:
        j, mois_txt, annee = m.groups()
        try:
            d = date(int(annee), MOIS[mois_txt.lower()], int(j))
            return d, d
        except ValueError:
            return None, None

    return None, None


def parser_semaine(semaine_texte: str):
    """Convertit le champ texte 'semaine' du JSON source (ex: '21-25 sept
    2026 a 26-30 oct 2026') en (date_debut, date_fin) couvrant toute la
    periode du chapitre. Retourne (None, None) si non parsable -- le
    chapitre est quand meme insere (dates NULL) pour ne rien perdre, mais
    il ne remontera pas dans une recherche par date tant qu'il n'est pas
    corrige manuellement."""
    if not semaine_texte:
        return None, None

    blocs = [b.strip() for b in re.split(r"\s+a\s+", semaine_texte) if b.strip()]
    if not blocs:
        return None, None

    debut, _ = _parse_un_bloc_date(blocs[0])
    _, fin = _parse_un_bloc_date(blocs[-1])

    if debut and not fin:
        fin = debut
    if fin and not debut:
        debut = fin

    return debut, fin


def importer_json_progression(chemin_json: str, matiere: str, annee_scolaire: str):
    """Importe un fichier JSON structure (format progression_minesec_2026_2027.json)
    dans Postgres pour une matiere donnee. Reutilisable pour Physique, SVT,
    etc. : il suffit de produire un JSON avec la meme structure
    (niveaux -> chapitres -> lecons) et d'appeler cette fonction avec
    matiere='PCT' par exemple.

    ON CONFLICT DO UPDATE (equivalent Postgres du INSERT OR REPLACE SQLite) :
    si on reimporte une version corrigee du meme fichier, on ecrase l'ancienne
    ligne au lieu de la dupliquer ou de la laisser perimee."""
    conn = get_connection()
    try:
        create_table()
        cur = conn.cursor()

        with open(chemin_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        compte_chapitres = 0
        compte_non_parses = 0
        niveaux = data.get("niveaux", {})

        for niveau_cle, contenu in niveaux.items():
            if "chapitres" in contenu:
                n = _inserer_chapitres(cur, matiere, annee_scolaire, niveau_cle,
                                        None, contenu["chapitres"])
                compte_chapitres += len(contenu["chapitres"])
                compte_non_parses += n
            else:
                for serie, sous_contenu in contenu.items():
                    chapitres = sous_contenu.get("chapitres", [])
                    n = _inserer_chapitres(cur, matiere, annee_scolaire, niveau_cle,
                                            serie, chapitres)
                    compte_chapitres += len(chapitres)
                    compte_non_parses += n

        meta = data.get("meta", {})
        calendrier = meta.get("calendrier_commun", {})

        for jour in calendrier.get("journees_notables", []):
            cur.execute("""
                INSERT INTO progressions_evenements
                (annee_scolaire, date_debut, date_fin, label)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (annee_scolaire, date_debut, label) DO NOTHING
            """, (annee_scolaire, jour["date"], jour.get("date_fin"), jour["label"]))

        for cle in ("interruption_1", "interruption_2", "epreuves_zero"):
            bloc = calendrier.get(cle)
            if bloc:
                cur.execute("""
                    INSERT INTO progressions_evenements
                    (annee_scolaire, date_debut, date_fin, label)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (annee_scolaire, date_debut, label) DO NOTHING
                """, (annee_scolaire, bloc["debut"], bloc.get("fin"),
                      bloc.get("label", cle)))

        conn.commit()
        print(f"{compte_chapitres} chapitres importes pour {matiere} "
              f"({annee_scolaire}), {compte_non_parses} avec dates non "
              f"parsables (verifier manuellement).")
    except Exception as e:
        conn.rollback()
        print(f"importer_json_progression error: {e}")
        raise
    finally:
        conn.close()


def _inserer_chapitres(cur, matiere, annee_scolaire, niveau, serie, chapitres):
    non_parses = 0
    for chap in chapitres:
        debut, fin = parser_semaine(chap.get("semaine", ""))
        if debut is None:
            non_parses += 1
        cur.execute("""
            INSERT INTO progressions_chapitres
            (annee_scolaire, matiere, niveau, serie, ordre, nom_chapitre,
             lecons, semaine_texte, date_debut, date_fin, evaluation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (annee_scolaire, matiere, niveau, serie, ordre)
            DO UPDATE SET
                nom_chapitre = EXCLUDED.nom_chapitre,
                lecons = EXCLUDED.lecons,
                semaine_texte = EXCLUDED.semaine_texte,
                date_debut = EXCLUDED.date_debut,
                date_fin = EXCLUDED.date_fin,
                evaluation = EXCLUDED.evaluation
        """, (
            annee_scolaire, matiere, niveau, serie, chap["ordre"], chap["nom"],
            json.dumps(chap.get("lecons", []), ensure_ascii=False),
            chap.get("semaine"), debut, fin, chap.get("evaluation"),
        ))
    return non_parses


def obtenir_progression_du_jour(matiere: str, niveau: str, serie: Optional[str] = None,
                                 date_reference: Optional[date] = None) -> dict:
    """Fonction principale a appeler depuis chat_contexte.py avant de
    construire le prompt systeme. Retourne un dict avec 'disponible': False
    si rien n'est trouve -- dans ce cas ne JAMAIS laisser Gemini deviner un
    contenu de programme a la place."""
    date_reference = date_reference or date.today()
    conn = get_connection()
    resultat = {"disponible": False, "date_reference": date_reference.isoformat()}

    try:
        cur = conn.cursor()

        # serie IS NULL cote base ne matche pas '= %s' en SQL standard :
        # meme logique que get_annales() dans database.py.
        cur.execute("""
            SELECT * FROM progressions_chapitres
            WHERE matiere = %s AND niveau = %s
              AND (serie = %s OR (%s IS NULL AND serie IS NULL))
              AND date_debut IS NOT NULL AND date_fin IS NOT NULL
              AND date_debut <= %s AND date_fin >= %s
            ORDER BY ordre LIMIT 1
        """, (matiere, niveau, serie, serie, date_reference, date_reference))
        row = cur.fetchone()

        if row:
            resultat.update({
                "disponible": True,
                "chapitre_ordre": row["ordre"],
                "chapitre_nom": row["nom_chapitre"],
                "lecons": json.loads(row["lecons"]),
                "periode": f"{row['date_debut']} au {row['date_fin']}",
                "evaluation": row["evaluation"],
            })
        else:
            cur.execute("""
                SELECT * FROM progressions_chapitres
                WHERE matiere = %s AND niveau = %s
                  AND (serie = %s OR (%s IS NULL AND serie IS NULL))
                  AND date_debut IS NOT NULL AND date_debut > %s
                ORDER BY date_debut LIMIT 1
            """, (matiere, niveau, serie, serie, date_reference))
            row_suivant = cur.fetchone()
            if row_suivant:
                resultat["prochain_chapitre"] = row_suivant["nom_chapitre"]
                resultat["prochain_chapitre_debut"] = row_suivant["date_debut"].isoformat()

        cur.execute("""
            SELECT label, date_debut, date_fin FROM progressions_evenements
            WHERE date_debut <= %s
              AND ((date_fin IS NULL AND date_debut = %s) OR date_fin >= %s)
        """, (date_reference, date_reference, date_reference))
        resultat["evenements_du_jour"] = [dict(e) for e in cur.fetchall()]

    except Exception as e:
        print(f"obtenir_progression_du_jour error: {e}")
        resultat["evenements_du_jour"] = []
    finally:
        conn.close()

    return resultat


def texte_pour_prompt_systeme(matiere: str, niveau: str, serie: Optional[str] = None,
                               date_reference: Optional[date] = None) -> str:
    """Formate obtenir_progression_du_jour() en un bloc de texte pret a
    coller dans le prompt systeme Gemini. Garde-fou : si rien n'est
    disponible, le dit explicitement plutot que de laisser un trou que le
    modele pourrait combler par hallucination."""
    info = obtenir_progression_du_jour(matiere, niveau, serie, date_reference)
    jour_lisible = datetime.fromisoformat(info["date_reference"]).strftime("%d/%m/%Y")

    lignes = [f"[PROGRESSION NATIONALE MINESEC - {matiere} - {niveau}"
              + (f" serie {serie}" if serie else "") + f" - date du jour: {jour_lisible}]"]

    for ev in info.get("evenements_du_jour", []):
        lignes.append(f"- Evenement du jour: {ev['label']}")

    if info["disponible"]:
        lignes.append(f"- Chapitre officiel en cours (semaine du {info['periode']}): "
                       f"{info['chapitre_nom']}")
        lignes.append(f"- Lecons de ce chapitre: {', '.join(info['lecons'])}")
        if info.get("evaluation"):
            lignes.append(f"- Evaluation prevue: {info['evaluation']}")
        lignes.append("- Consigne: base tes reponses pedagogiques sur ce chapitre en "
                       "priorite si l'eleve ne precise pas un autre sujet.")
    else:
        if info.get("prochain_chapitre"):
            lignes.append(f"- Aucun chapitre officiel en cours aujourd'hui (periode de "
                           f"vacances/interruption ou hors calendrier). Prochain chapitre "
                           f"prevu: {info['prochain_chapitre']} (a partir du "
                           f"{info['prochain_chapitre_debut']}).")
        else:
            lignes.append("- Aucune donnee de progression disponible pour cette date/serie. "
                           "Ne pas affirmer de position dans le programme officiel: repondre "
                           "sur le fond mathematique uniquement.")

    return "\n".join(lignes)


if __name__ == "__main__":
    # Test rapide : python database_progressions.py
    create_table()
    print(texte_pour_prompt_systeme("Mathematiques", "terminale", "C-E"))