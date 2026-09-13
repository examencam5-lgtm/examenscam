import json
import sqlite3

DB = "data/rag_maths_bac_c/rag.db"
JSON_PATH = "data/progression_physique_2026_2027.json"

def abrev_niveau(niveau):
    return "TC" if niveau == "terminale" else "1"

def get_or_create_theme(conn, numero_chapitre, nom_theme, matiere, niveau, serie):
    row = conn.execute(
        """SELECT id FROM themes
           WHERE numero_chapitre=? AND matiere=? AND niveau=? AND serie=?""",
        (numero_chapitre, matiere, niveau, serie)
    ).fetchone()
    if row:
        return row[0], False

    cur = conn.execute(
        """INSERT INTO themes (numero_chapitre, nom_theme, matiere, niveau, serie)
           VALUES (?,?,?,?,?)""",
        (numero_chapitre, nom_theme, matiere, niveau, serie)
    )
    return cur.lastrowid, True

def importer_physique():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    conn = sqlite3.connect(DB)
    nb_themes = 0
    nb_lecons = 0
    nb_ignorees = 0

    for niveau in ["terminale", "premiere"]:
        for serie in ["C", "D", "TI"]:
            chapitres = data["niveaux"][niveau][serie]["chapitres"]

            for chap in chapitres:
                numero_chapitre = chap["ordre"]
                nom_theme = chap["nom"]

                theme_id, cree = get_or_create_theme(
                    conn, numero_chapitre, nom_theme, "Physique", niveau, serie
                )
                if cree:
                    nb_themes += 1

                for i, lecon in enumerate(chap.get("lecons", []), start=1):
                    identifiant = f"PHY_{abrev_niveau(niveau)}_{serie}_{numero_chapitre}_{i}"
                    titre = lecon["titre"]

                    cur = conn.execute(
                        """INSERT OR IGNORE INTO lecons
                           (theme_id, matiere, chapitre_numero, lecon_numero,
                            identifiant, titre, niveau)
                           VALUES (?,?,?,?,?,?,?)""",
                        (theme_id, "Physique", numero_chapitre, i,
                         identifiant, titre, niveau)
                    )
                    if cur.rowcount == 1:
                        nb_lecons += 1
                    else:
                        nb_ignorees += 1

    conn.commit()
    conn.close()
    print(f"\n{nb_themes} nouveaux themes, {nb_lecons} nouvelles lecons, {nb_ignorees} deja existantes (ignorees)")

if __name__ == "__main__":
    importer_physique()