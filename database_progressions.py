# database_progressions.py — ExamensCam
"""
Stocke les fiches de progression harmonisee nationale MINESEC (une par matiere
et par annee scolaire) et les evenements du calendrier scolaire, pour
interrogation par date. C'est la source de verite qui remplace toute
connaissance generique et potentiellement perimee que Gemini pourrait avoir
sur le programme et le calendrier camerounais.

Meme stack que database.py : Postgres gere chez Neon via DATABASE_URL,
psycopg2, RealDictCursor, placeholders %s, rollback() explicite sur erreur
d'ecriture.

CORRECTIF (17/09/2026) -- normalisation lecons + chapitres simultanes :
1. Le JSON Maths utilise lecons=[str,...], le JSON Physique utilise
   lecons=[{"titre":..., "duree_heures":...}]. L'ancienne version stockait
   le format brut tel quel (json.dumps direct) -- texte_pour_prompt_systeme()
   plantait en TypeError des le premier ', '.join(lecons) sur une liste de
   dicts, ce qui aurait casse toute injection Physique en production. Voir
   _normaliser_lecons().
2. Le JSON source contient des chapitres avec la MEME semaine (ex: Physique
   Terminale C, ordres 16/17/18 tous "15-19 mars 2027") -- l'ancien
   obtenir_progression_du_jour() faisait ORDER BY ordre LIMIT 1 et perdait
   silencieusement les chapitres paralleles. Retourne desormais TOUJOURS une
   liste sous la cle 'chapitres', meme s'il n'y en a qu'un seul.

CORRECTIF (07/09/2026) -- ajout de la table progressions_niveaux :
horaire_hebdo et nombre_chapitres existent dans le JSON source (au niveau
du contenu, avant la liste "chapitres") mais n'etaient stockes nulle part
en base -- voir _inserer_meta_niveau() et obtenir_horaire_hebdo().
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
                lecons          TEXT NOT NULL,      -- JSON liste de titres (str), stocke en texte
                semaine_texte   TEXT,
                date_debut      DATE,
                date_fin        DATE,
                evaluation      TEXT,
                UNIQUE(annee_scolaire, matiere, niveau, serie, ordre)
            );
        """)
        # CORRECTIF (17/09/2026) : lecons_detail conserve duree_heures
        # (present dans le JSON Physique, absent du JSON Maths) sans
        # jamais l'inventer pour les chapitres qui ne l'ont pas -- voir
        # _normaliser_lecons(). ADD COLUMN IF NOT EXISTS : idempotent
        # sur une base deja peuplee, ne touche a aucune ligne existante.
        cur.execute("""
            ALTER TABLE progressions_chapitres
            ADD COLUMN IF NOT EXISTS lecons_detail TEXT;
        """)
        cur.execute("""
            ALTER TABLE progressions_niveaux
            ADD COLUMN IF NOT EXISTS volume_horaire_calcule INTEGER;
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS progressions_niveaux (
                id                    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                annee_scolaire        TEXT NOT NULL,
                matiere               TEXT NOT NULL,
                niveau                TEXT NOT NULL,
                serie                 TEXT,
                horaire_hebdo         TEXT,
                nombre_chapitres      INTEGER,
                evaluation_fin_annee  TEXT,
                UNIQUE(annee_scolaire, matiere, niveau, serie)
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


def _normaliser_lecons(lecons_brutes: list) -> tuple[list[str], list[dict]]:
    """CORRECTIF (17/09/2026) : le JSON Maths utilise lecons=[str,...],
    le JSON Physique utilise lecons=[{"titre":..., "duree_heures":...}].
    Sans cette normalisation, json.dumps() stockait le format brut tel
    quel, et texte_pour_prompt_systeme() plantait (TypeError) au premier
    ', '.join(lecons) sur une liste de dicts -- bug qui aurait casse
    toute injection Physique en production des le premier appel.

    Retourne (titres, detail) :
      - titres : liste de str, compatible avec tout le code existant qui
        fait ', '.join(lecons) -- format de sortie UNIQUE quelle que soit
        la matiere source.
      - detail : liste de {titre, duree_heures} uniquement quand
        duree_heures existe dans le JSON source, sinon [] -- jamais
        invente pour une matiere (ex: Maths) qui ne fournit pas cette
        info."""
    titres, detail = [], []
    for l in lecons_brutes:
        if isinstance(l, str):
            titres.append(l)
        elif isinstance(l, dict):
            titre = l.get("titre", "")
            titres.append(titre)
            if "duree_heures" in l:
                detail.append({"titre": titre, "duree_heures": l["duree_heures"]})
    return titres, detail


def _inserer_meta_niveau(cur, annee_scolaire, matiere, niveau, serie, contenu):
    """Capture horaire_hebdo/nombre_chapitres/evaluation_fin_annee depuis
    le meme dict `contenu` que celui deja parcouru pour les chapitres --
    rien a relire depuis le fichier JSON.

    NOTE : le JSON Physique fourni par Muhammad n'a PAS ces champs au
    niveau serie (contrairement au JSON Maths) -- contenu.get() renvoie
    alors None et rien n'est invente. obtenir_horaire_hebdo() renverra
    'disponible': False pour la Physique tant que le JSON source n'est
    pas complete avec horaire_hebdo/nombre_chapitres."""
    cur.execute("""
        INSERT INTO progressions_niveaux
        (annee_scolaire, matiere, niveau, serie, horaire_hebdo, nombre_chapitres, evaluation_fin_annee)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (annee_scolaire, matiere, niveau, serie)
        DO UPDATE SET
            horaire_hebdo = EXCLUDED.horaire_hebdo,
            nombre_chapitres = EXCLUDED.nombre_chapitres,
            evaluation_fin_annee = EXCLUDED.evaluation_fin_annee
    """, (
        annee_scolaire, matiere, niveau, serie,
        contenu.get("horaire_hebdo"), contenu.get("nombre_chapitres"),
        contenu.get("evaluation_fin_annee"),
    ))


def importer_json_progression(chemin_json: str, matiere: str, annee_scolaire: str):
    """Importe un fichier JSON structure (format progression_minesec_2026_2027.json)
    dans Postgres pour une matiere donnee. Reutilisable pour Chimie, SVT,
    etc. : il suffit de produire un JSON avec la meme structure
    (niveaux -> chapitres -> lecons) et d'appeler cette fonction avec
    matiere='Chimie' par exemple.

    ON CONFLICT DO UPDATE : si on reimporte une version corrigee du meme
    fichier, on ecrase l'ancienne ligne au lieu de la dupliquer.

    Le calendrier commun (meta.calendrier_commun) n'existe que dans le
    JSON Maths -- le JSON Physique n'a pas de bloc "meta" avec ce
    contenu. Ce n'est pas un probleme : progressions_evenements n'a pas
    de colonne matiere (le calendrier scolaire est national, pas
    specifique a une matiere), donc l'importer une seule fois via
    n'importe quel JSON qui le contient suffit -- ON CONFLICT DO NOTHING
    evite toute duplication si on l'importe plusieurs fois."""
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
                # Cas plat, ex: "3e" -- pas de sous-decoupage par serie.
                n = _inserer_chapitres(cur, matiere, annee_scolaire, niveau_cle,
                                        None, contenu["chapitres"])
                compte_chapitres += len(contenu["chapitres"])
                compte_non_parses += n
                _inserer_meta_niveau(cur, annee_scolaire, matiere, niveau_cle, None, contenu)
            else:
                # Cas par serie, ex: "premiere" -> "C"/"D"/"TI"/"A4".
                for serie, sous_contenu in contenu.items():
                    chapitres = sous_contenu.get("chapitres", [])
                    n = _inserer_chapitres(cur, matiere, annee_scolaire, niveau_cle,
                                            serie, chapitres)
                    compte_chapitres += len(chapitres)
                    compte_non_parses += n
                    _inserer_meta_niveau(cur, annee_scolaire, matiere, niveau_cle, serie, sous_contenu)

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
    """CORRECTIF (17/09/2026) : normalise `lecons` via _normaliser_lecons()
    avant stockage -- accepte indifferemment le format Maths (liste de
    str) et le format Physique (liste de dicts avec duree_heures), et
    stocke toujours des titres en str dans `lecons` (compatibilite avec
    tout le code existant), plus le detail complet dans `lecons_detail`
    quand il existe."""
    non_parses = 0
    for chap in chapitres:
        debut, fin = parser_semaine(chap.get("semaine", ""))
        if debut is None:
            non_parses += 1
        titres_lecons, detail_lecons = _normaliser_lecons(chap.get("lecons", []))
        cur.execute("""
            INSERT INTO progressions_chapitres
            (annee_scolaire, matiere, niveau, serie, ordre, nom_chapitre,
             lecons, lecons_detail, semaine_texte, date_debut, date_fin, evaluation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (annee_scolaire, matiere, niveau, serie, ordre)
            DO UPDATE SET
                nom_chapitre = EXCLUDED.nom_chapitre,
                lecons = EXCLUDED.lecons,
                lecons_detail = EXCLUDED.lecons_detail,
                semaine_texte = EXCLUDED.semaine_texte,
                date_debut = EXCLUDED.date_debut,
                date_fin = EXCLUDED.date_fin,
                evaluation = EXCLUDED.evaluation
        """, (
            annee_scolaire, matiere, niveau, serie, chap["ordre"], chap["nom"],
            json.dumps(titres_lecons, ensure_ascii=False),
            json.dumps(detail_lecons, ensure_ascii=False),
            chap.get("semaine"), debut, fin, chap.get("evaluation"),
        ))
    return non_parses


def obtenir_progression_du_jour(matiere: str, niveau: str, serie: Optional[str] = None,
                                 date_reference: Optional[date] = None) -> dict:
    """Fonction principale a appeler depuis chat_contexte.py avant de
    construire le prompt systeme. Retourne un dict avec 'disponible': False
    si rien n'est trouve -- dans ce cas ne JAMAIS laisser Gemini deviner un
    contenu de programme a la place.

    CORRECTIF (17/09/2026) : retourne desormais TOUS les chapitres actifs
    a cette date sous la cle 'chapitres' (toujours une liste, meme a un
    seul element) -- le JSON Physique a des chapitres qui partagent la
    meme semaine (ex: Terminale C, ordres 16/17/18 tous "15-19 mars 2027"),
    et l'ancien ORDER BY ordre LIMIT 1 en perdait deux sur trois
    silencieusement.

    Cles retro-compat conservees (chapitre_nom, lecons, periode,
    evaluation) pointant sur le PREMIER chapitre par ordre -- pour ne pas
    casser un appelant qui ne gere pas encore la liste, mais tout nouveau
    code (chat_contexte.py) doit lire 'chapitres' pour ne rien perdre."""
    date_reference = date_reference or date.today()
    conn = get_connection()
    resultat = {"disponible": False, "date_reference": date_reference.isoformat()}

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT * FROM progressions_chapitres
            WHERE matiere = %s AND niveau = %s
              AND (serie = %s OR (%s IS NULL AND serie IS NULL))
              AND date_debut IS NOT NULL AND date_fin IS NOT NULL
              AND date_debut <= %s AND date_fin >= %s
            ORDER BY ordre
        """, (matiere, niveau, serie, serie, date_reference, date_reference))
        rows = cur.fetchall()

        if rows:
            resultat["disponible"] = True
            resultat["chapitres"] = [{
                "ordre": r["ordre"],
                "nom_chapitre": r["nom_chapitre"],
                "lecons": json.loads(r["lecons"]),
                "lecons_detail": json.loads(r["lecons_detail"] or "[]"),  # AJOUT
                "periode": f"{r['date_debut']} au {r['date_fin']}",
                "evaluation": r["evaluation"],
            } for r in rows]

            premier = resultat["chapitres"][0]
            resultat.update({
                "chapitre_ordre": premier["ordre"],
                "chapitre_nom": premier["nom_chapitre"],
                "lecons": premier["lecons"],
                "periode": premier["periode"],
                "evaluation": premier["evaluation"],
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

def recalculer_volume_horaire_calcule(matiere: str, annee_scolaire: str = "2026-2027"):
    """Calcule, pour chaque niveau/serie, le volume horaire TOTAL annuel
    en sommant duree_heures depuis lecons_detail -- donnee deductible du
    JSON source (Physique en a, Maths n'en a pas). STOCKE DANS UNE
    COLONNE DEDIEE volume_horaire_calcule, JAMAIS confondue avec
    horaire_hebdo (donnee MINESEC officielle, distincte par nature : un
    rythme hebdomadaire fixe vs une somme annuelle calculee). Les
    confondre serait exactement le type d'hallucination que le prompt
    doit empecher -- donc deux champs, deux libelles distincts injectes
    separement dans texte_pour_prompt_systeme()."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT niveau, serie, lecons_detail
            FROM progressions_chapitres
            WHERE matiere = %s AND annee_scolaire = %s
        """, (matiere, annee_scolaire))
        rows = cur.fetchall()

        totaux = {}
        for r in rows:
            detail = json.loads(r["lecons_detail"] or "[]")
            if not detail:
                continue
            cle = (r["niveau"], r["serie"])
            totaux[cle] = totaux.get(cle, 0) + sum(d.get("duree_heures", 0) for d in detail)

        for (niveau, serie), total in totaux.items():
            cur.execute("""
                INSERT INTO progressions_niveaux
                (annee_scolaire, matiere, niveau, serie, volume_horaire_calcule)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (annee_scolaire, matiere, niveau, serie)
                DO UPDATE SET volume_horaire_calcule = EXCLUDED.volume_horaire_calcule
            """, (annee_scolaire, matiere, niveau, serie, total))

        conn.commit()
        print(f"Volume horaire calcule pour {len(totaux)} niveau(x)/serie(s) en {matiere}.")
    except Exception as e:
        conn.rollback()
        print(f"recalculer_volume_horaire_calcule error: {e}")
    finally:
        conn.close()


def obtenir_horaire_hebdo(matiere: str, niveau: str, serie: Optional[str] = None) -> dict:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT horaire_hebdo, nombre_chapitres, evaluation_fin_annee, volume_horaire_calcule
            FROM progressions_niveaux
            WHERE matiere = %s AND niveau = %s
              AND (serie = %s OR (%s IS NULL AND serie IS NULL))
            LIMIT 1
        """, (matiere, niveau, serie, serie))
        row = cur.fetchone()
        if not row:
            return {"disponible": False}
        return {"disponible": True, **dict(row)}
    except Exception as e:
        print(f"obtenir_horaire_hebdo error: {e}")
        return {"disponible": False}
    finally:
        conn.close()
def obtenir_chronologie(matiere: str, niveau: str, serie: Optional[str] = None,
                         annee_scolaire: str = "2026-2027") -> list[dict]:
    """Retourne TOUS les chapitres d'un niveau/serie/matiere, dans l'ordre,
    avec leurs dates -- pour repondre a une demande de calendrier complet
    ou de trimestre, par opposition a obtenir_progression_du_jour() qui
    ne regarde QUE la date du jour meme. Filtre strictement par matiere :
    un eleve BAC C Physique ne recoit jamais une ligne de BAC C
    Mathematiques ou de BAC D Physique, la clause WHERE matiere=%s AND
    niveau=%s AND serie=%s l'exclut structurellement au niveau SQL."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT ordre, nom_chapitre, semaine_texte, date_debut, date_fin, evaluation
            FROM progressions_chapitres
            WHERE matiere = %s AND niveau = %s AND annee_scolaire = %s
              AND (serie = %s OR (%s IS NULL AND serie IS NULL))
            ORDER BY ordre
        """, (matiere, niveau, annee_scolaire, serie, serie))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"obtenir_chronologie error: {e}")
        return []
    finally:
        conn.close()


def obtenir_chapitre_a_date(matiere: str, niveau: str, serie: Optional[str],
                             date_cible: date) -> dict:
    """Meme logique que obtenir_progression_du_jour() mais pour une
    date ARBITRAIRE (passee ou future dans l'annee scolaire), pas
    seulement aujourd'hui -- reponse a 'le 12 janvier on fait quoi'.
    Simple alias explicite."""
    return obtenir_progression_du_jour(matiere, niveau, serie, date_reference=date_cible)
def obtenir_date_rentree(matiere: str, niveau: str, serie: Optional[str] = None,
                          annee_scolaire: str = "2026-2027") -> Optional[date]:
    """Retourne la date de debut du PREMIER chapitre (date la plus basse
    connue) pour ce niveau/serie/matiere -- reponse deterministe a 'la
    rentree c'est quand', jamais laissee a Gemini qui n'a aucune raison
    de connaitre cette date avec precision."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT MIN(date_debut) AS premiere_date
            FROM progressions_chapitres
            WHERE matiere = %s AND niveau = %s AND annee_scolaire = %s
              AND (serie = %s OR (%s IS NULL AND serie IS NULL))
              AND date_debut IS NOT NULL
        """, (matiere, niveau, annee_scolaire, serie, serie))
        row = cur.fetchone()
        return row["premiere_date"] if row else None
    except Exception as e:
        print(f"obtenir_date_rentree error: {e}")
        return None
    finally:
        conn.close()


def texte_pour_prompt_systeme(matiere: str, niveau: str, serie: Optional[str] = None,
                               date_reference: Optional[date] = None) -> str:
    info = obtenir_progression_du_jour(matiere, niveau, serie, date_reference)
    jour_lisible = datetime.fromisoformat(info["date_reference"]).strftime("%d/%m/%Y")

    lignes = [f"[PROGRESSION NATIONALE MINESEC - {matiere} - {niveau}"
              + (f" serie {serie}" if serie else "") + f" - date du jour: {jour_lisible}]"]

    meta = obtenir_horaire_hebdo(matiere, niveau, serie)
    if meta.get("disponible"):
        if meta.get("horaire_hebdo"):
            lignes.append(f"- Horaire hebdomadaire officiel MINESEC : {meta['horaire_hebdo']}")
        elif meta.get("volume_horaire_calcule"):
            lignes.append(f"- Volume horaire total ANNUEL calculé depuis le découpage du "
                           f"programme (PAS un rythme hebdomadaire officiel) : "
                           f"{meta['volume_horaire_calcule']}h sur l'année")
        if meta.get("nombre_chapitres"):
            lignes.append(f"- Nombre total de chapitres au programme : {meta['nombre_chapitres']}")

    for ev in info.get("evenements_du_jour", []):
        lignes.append(f"- Evenement du jour: {ev['label']}")

    def _ligne_lecons(c: dict) -> str:
        """AJOUT : affiche la durée par leçon quand lecons_detail existe
        (cas Physique), sinon juste les titres (cas Maths, qui n'a pas
        cette granularité dans son JSON source -- jamais inventé)."""
        if c.get("lecons_detail"):
            return ", ".join(f"{d['titre']} ({d['duree_heures']}h)" for d in c["lecons_detail"])
        return ", ".join(c["lecons"])

    if info["disponible"]:
        chapitres = info["chapitres"]
        if len(chapitres) == 1:
            c = chapitres[0]
            lignes.append(f"- Chapitre officiel en cours (semaine du {c['periode']}): "
                           f"{c['nom_chapitre']}")
            lignes.append(f"- Lecons de ce chapitre: {_ligne_lecons(c)}")
            if c.get("evaluation"):
                lignes.append(f"- Evaluation prevue: {c['evaluation']}")
        else:
            lignes.append(f"- {len(chapitres)} chapitres officiels menes en parallele "
                           f"cette periode :")
            for c in chapitres:
                ligne = f"  - {c['nom_chapitre']} (lecons: {_ligne_lecons(c)})"
                if c.get("evaluation"):
                    ligne += f" -- evaluation: {c['evaluation']}"
                lignes.append(ligne)
        lignes.append("- Consigne: base tes reponses pedagogiques sur ce(s) chapitre(s) en "
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
    print(texte_pour_prompt_systeme("Mathematiques", "terminale", "C"))
    print()
    print(texte_pour_prompt_systeme("Physique", "terminale", "C"))

def recalculer_nombre_chapitres(matiere: str, annee_scolaire: str = "2026-2027"):
    """Deduit nombre_chapitres directement de progressions_chapitres
    (COUNT reel) plutot que de dependre d'un champ JSON source qui peut
    manquer (cas du JSON Physique actuel) ou se desynchroniser d'un futur
    ajout/suppression de chapitre. Ne touche PAS horaire_hebdo ni
    evaluation_fin_annee -- ces deux champs restent des donnees MINESEC
    officielles qui ne peuvent pas etre deduites, seulement fournies."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT niveau, serie, COUNT(*) AS nb
            FROM progressions_chapitres
            WHERE matiere = %s AND annee_scolaire = %s
            GROUP BY niveau, serie
        """, (matiere, annee_scolaire))
        lignes = cur.fetchall()

        for l in lignes:
            cur.execute("""
                INSERT INTO progressions_niveaux
                (annee_scolaire, matiere, niveau, serie, nombre_chapitres)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (annee_scolaire, matiere, niveau, serie)
                DO UPDATE SET nombre_chapitres = EXCLUDED.nombre_chapitres
            """, (annee_scolaire, matiere, l["niveau"], l["serie"], l["nb"]))

        conn.commit()
        print(f"nombre_chapitres recalcule pour {len(lignes)} niveau(x)/serie(s) en {matiere}.")
    except Exception as e:
        conn.rollback()
        print(f"recalculer_nombre_chapitres error: {e}")
    finally:
        conn.close()