# diagnostic_sequences.py
"""
Diagnostic ponctuel -- répond à une seule question : pour chaque
séquence 1 à 6, combien d'annales brutes sont importées, et combien
sont réellement structurées (thèmes + barèmes présents) et donc
utilisables par generer_epreuve_json.py ?

Usage :
    python diagnostic_sequences.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("data/rag_maths_bac_c/rag.db")


def main():
    if not DB_PATH.exists():
        print(f"❌ Base introuvable : {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)

    print(f"{'Séq.':<6}{'Annales brutes importées':<28}{'Structurées (utilisables)':<28}")
    print("-" * 62)

    for sequence in range(1, 7):
        nb_brutes = conn.execute("""
            SELECT COUNT(*) FROM epreuves
            WHERE sequence = ? AND type_document = 'sequence' AND matiere_suspecte = 0
        """, (sequence,)).fetchone()[0]

        nb_structurees = conn.execute("""
            SELECT COUNT(DISTINCT e.id)
            FROM epreuves e
            JOIN parties p ON p.epreuve_id = e.id
            JOIN exercices ex ON ex.partie_id = p.id
            JOIN exercice_themes et ON et.exercice_id = ex.id
            WHERE e.sequence = ? AND e.type_document = 'sequence' AND e.matiere_suspecte = 0
        """, (sequence,)).fetchone()[0]

        alerte = ""
        if nb_brutes == 0:
            alerte = "  <- rien importé (étape scan Drive/CSV)"
        elif nb_structurees == 0:
            alerte = "  <- importé mais pas structuré (relancer extraire_structure_gemini.py)"

        print(f"{sequence:<6}{nb_brutes:<28}{nb_structurees:<28}{alerte}")

    conn.close()


if __name__ == "__main__":
    main()