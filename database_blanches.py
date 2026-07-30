# database_blanches.py
"""
Fonctions d'accÃ¨s Ã la table 'annales_blanches'.
Contrairement aux Ã©tablissements (scraping automatique), ce contenu
est ajoutÃ© par Muhammad lui-mÃªme -- ces fonctions sont donc pensÃ©es
pour un usage simple, ligne par ligne ou en petit lot.

Import dans app.py :
    from database_blanches import ajouter_epreuve_blanche, get_epreuves_blanches
"""

import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path('data') / 'annales.db'


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ajouter_epreuve_blanche(niveau: str, matiere: str, annee: int, lien_drive: str,
                             serie: Optional[str] = None, region: Optional[str] = None,
                             sequence: Optional[int] = None,
                             type_evaluation: str = "Bac blanc",
                             titre: Optional[str] = None,
                             source: Optional[str] = None) -> Optional[int]:
    """
    Ajoute une Ã©preuve blanche. Retourne son ID, ou None si elle
    existe dÃ©jÃ (mÃªme niveau+serie+matiere+annee+region+sequence+type).

    IMPORTANT : en SQL, NULL n'est jamais Ã©gal Ã NULL, mÃªme dans une
    contrainte UNIQUE -- deux lignes avec sequence=NULL ne sont JAMAIS
    dÃ©tectÃ©es comme doublons. On utilise donc des valeurs sentinelles
    ('' pour rÃ©gion, 0 pour sÃ©quence) Ã la place de None, pour que
    l'unicitÃ© fonctionne rÃ©ellement.
    """
    region_normalisee = region or ""
    sequence_normalisee = sequence if sequence is not None else 0

    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO annales_blanches
                (niveau, serie, matiere, annee, titre, region, sequence,
                 type_evaluation, lien_drive, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (niveau, serie, matiere, annee, titre, region_normalisee, sequence_normalisee,
              type_evaluation, lien_drive, source))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        print(f"âš ï¸ Cette Ã©preuve blanche existe dÃ©jÃ (mÃªme niveau/sÃ©rie/matiÃ¨re/annÃ©e/rÃ©gion/sÃ©quence/type).")
        return None
    finally:
        conn.close()


def get_epreuves_blanches(niveau: str, matiere: str, serie: Optional[str] = None,
                           region: Optional[str] = None) -> list[dict]:
    """
    Liste les Ã©preuves blanches disponibles, filtrables par rÃ©gion.
    UtilisÃ© pour peupler la page de la branche 3 (Ã‰noncÃ©s blancs).
    """
    conn = get_connection()

    query = "SELECT * FROM annales_blanches WHERE niveau=? AND matiere=? AND actif=1"
    params = [niveau, matiere]

    if serie:
        query += " AND serie=?"
        params.append(serie)
    if region:
        query += " AND region=?"
        params.append(region)

    query += " ORDER BY annee DESC, region"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_regions_disponibles(niveau: str, matiere: str, serie: Optional[str] = None) -> list[str]:
    """
    Retourne la liste des rÃ©gions ayant au moins une Ã©preuve blanche,
    pour peupler un filtre Ã onglets sur la page (comme pour les
    sÃ©quences des Ã©tablissements).
    """
    conn = get_connection()

    query = "SELECT DISTINCT region FROM annales_blanches WHERE niveau=? AND matiere=? AND actif=1 AND region != ''"
    params = [niveau, matiere]
    if serie:
        query += " AND serie=?"
        params.append(serie)
    query += " ORDER BY region"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [r[0] for r in rows]


if __name__ == "__main__":
    # Auto-test rapide
    id1 = ajouter_epreuve_blanche(
        "BAC", "Mathematiques", 2026, "https://drive.google.com/exemple-ouest",
        serie="C", region="Ouest", type_evaluation="HarmonisÃ© rÃ©gional",
        titre="Bac Blanc HarmonisÃ© Ouest 2026"
    )
    print("Ã‰preuve crÃ©Ã©e, id =", id1)

    # Tentative de doublon exact -- doit Ã©chouer proprement
    id2 = ajouter_epreuve_blanche(
        "BAC", "Mathematiques", 2026, "https://drive.google.com/autre-lien",
        serie="C", region="Ouest", type_evaluation="HarmonisÃ© rÃ©gional",
        titre="Bac Blanc HarmonisÃ© Ouest 2026 (doublon)"
    )
    print("Tentative doublon, rÃ©sultat =", id2, "(doit Ãªtre None)")

    print("Ã‰preuves BAC C Maths :", get_epreuves_blanches("BAC", "Mathematiques", serie="C"))
    print("RÃ©gions disponibles :", get_regions_disponibles("BAC", "Mathematiques", serie="C"))
