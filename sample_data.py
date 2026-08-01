"""
sample_data.py — ExamensCam
Echantillonne des lignes reelles pour verifier deux choses precises :

1. La table 'annales' contient-elle des lignes 'annales_blanches' /
   'annales_externes' deguisees (type_hebergement != 'interne') ?
2. 'annales_externes.lien_externe' contient-il des liens vers des
   pages articles, ou des liens directs vers des fichiers PDF ?
   (Decision strategique section 4 du document : ca doit etre la
   page article, jamais le PDF direct.)

Usage :
    python sample_data.py
"""
import sqlite3
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'


def sample():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("=" * 70)
    print("1. TABLE 'annales' — repartition par type_hebergement")
    print("=" * 70)
    rows = conn.execute("""
        SELECT type_hebergement, COUNT(*) as n
        FROM annales
        GROUP BY type_hebergement
    """).fetchall()
    for r in rows:
        print(f"  type_hebergement = {r['type_hebergement']!r:<15} -> {r['n']} lignes")

    print("\n  Repartition par type_sujet :")
    rows = conn.execute("""
        SELECT type_sujet, COUNT(*) as n
        FROM annales
        GROUP BY type_sujet
    """).fetchall()
    for r in rows:
        print(f"  type_sujet = {r['type_sujet']!r:<15} -> {r['n']} lignes")

    print("\n  Lignes avec etablissement/lien_externe renseignes (hors NULL/'') :")
    rows = conn.execute("""
        SELECT COUNT(*) as n FROM annales
        WHERE (etablissement IS NOT NULL AND etablissement != '')
           OR (lien_externe IS NOT NULL AND lien_externe != '')
    """).fetchone()
    print(f"  -> {rows['n']} lignes")

    print("\n" + "=" * 70)
    print("2. TABLE 'annales_externes' — echantillon de 10 lignes")
    print("   (lien_externe vs lien_page_source)")
    print("=" * 70)
    rows = conn.execute("""
        SELECT id, titre, etablissement, lien_externe, lien_page_source, source_site
        FROM annales_externes
        ORDER BY RANDOM()
        LIMIT 10
    """).fetchall()
    for r in rows:
        print(f"\n  id={r['id']} | etablissement={r['etablissement']!r} | source_site={r['source_site']!r}")
        print(f"    lien_externe      = {r['lien_externe']}")
        print(f"    lien_page_source  = {r['lien_page_source']}")

    print("\n  Combien de lignes ont lien_page_source rempli vs vide :")
    rows = conn.execute("""
        SELECT
            SUM(CASE WHEN lien_page_source IS NOT NULL AND lien_page_source != '' THEN 1 ELSE 0 END) as rempli,
            SUM(CASE WHEN lien_page_source IS NULL OR lien_page_source = '' THEN 1 ELSE 0 END) as vide
        FROM annales_externes
    """).fetchone()
    print(f"  -> rempli = {rows['rempli']} | vide = {rows['vide']}")

    print("\n  lien_externe se termine-t-il souvent par .pdf ? (indice PDF direct)")
    rows = conn.execute("""
        SELECT
            SUM(CASE WHEN lien_externe LIKE '%.pdf%' THEN 1 ELSE 0 END) as finit_pdf,
            SUM(CASE WHEN lien_externe NOT LIKE '%.pdf%' THEN 1 ELSE 0 END) as pas_pdf
        FROM annales_externes
    """).fetchone()
    print(f"  -> se termine .pdf = {rows['finit_pdf']} | pas .pdf = {rows['pas_pdf']}")

    print("\n" + "=" * 70)
    print("3. TABLE 'annales_blanches' — echantillon complet (11 lignes)")
    print("=" * 70)
    rows = conn.execute("SELECT * FROM annales_blanches").fetchall()
    for r in rows:
        print(f"  id={r['id']} | {r['niveau']} {r['serie']} {r['matiere']} {r['annee']} | region={r['region']!r} | sequence={r['sequence']}")

    conn.close()


if __name__ == '__main__':
    sample()