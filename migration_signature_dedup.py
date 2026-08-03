"""
migration_signature_dedup.py — ExamensCam
Ajoute une colonne 'signature_dedup' a annales_externes, calculee a
partir de (niveau, serie, matiere, annee, etablissement normalise,
sequence). Objectif : detecter le MEME devoir scrape sur deux sites
differents (sujetexa ET epreuvesetcorriges), qui aura deux
lien_externe differents (deux domaines) mais la meme signature.

IMPORTANT : cette dedup est heuristique, pas parfaite -- deux devoirs
reellement differents du meme etablissement/matiere/annee/sequence
(rare mais possible, ex. deux devoirs de sequences differentes mal
detectees) seraient fusionnes a tort. Accepte comme compromis : mieux
vaut un faux doublon evite qu'une base saturee de vrais doublons.

Usage (une seule fois) :
    python migration_signature_dedup.py
"""
import sqlite3
import unicodedata
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'


def normaliser_etablissement(nom):
    """Meme logique que normaliser() dans generer_search_index.py --
    reutilisee ici pour que deux ecritures differentes du meme
    etablissement ('LYCEE CLASSIQUE D'EDEA' vs 'Lycee classique
    d'Edea') produisent la meme signature."""
    if not nom:
        return ""
    nom = nom.lower()
    nom = unicodedata.normalize('NFKD', nom)
    nom = ''.join(c for c in nom if not unicodedata.combining(c))
    for char in "'’-_.,":
        nom = nom.replace(char, ' ')
    return ' '.join(nom.split())


def calculer_signature(niveau, serie, matiere, annee, etablissement, sequence):
    parties = [
        (niveau or "").lower(),
        (serie or "").lower(),
        (matiere or "").lower(),
        str(annee or ""),
        normaliser_etablissement(etablissement),
        str(sequence or ""),
    ]
    return "|".join(parties)


def migrer():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Ajoute la colonne si elle n'existe pas deja -- migration idempotente,
    # relancer ce script sans risque ne duplique rien
    colonnes = [r['name'] for r in conn.execute("PRAGMA table_info(annales_externes)").fetchall()]
    if 'signature_dedup' not in colonnes:
        conn.execute("ALTER TABLE annales_externes ADD COLUMN signature_dedup TEXT")
        print("Colonne signature_dedup ajoutee.")
    else:
        print("Colonne signature_dedup deja presente.")

    # Calcule la signature pour toutes les lignes existantes
    rows = conn.execute("SELECT id, niveau, serie, matiere, annee, etablissement, sequence FROM annales_externes").fetchall()
    for r in rows:
        sig = calculer_signature(r['niveau'], r['serie'], r['matiere'], r['annee'], r['etablissement'], r['sequence'])
        conn.execute("UPDATE annales_externes SET signature_dedup = ? WHERE id = ?", (sig, r['id']))

    conn.commit()

    # Index (pas UNIQUE ici -- on veut d'abord voir combien de doublons
    # existent deja avant de bloquer les futurs inserts)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ext_signature ON annales_externes(signature_dedup)")
    conn.commit()

    # Rapport : combien de doublons potentiels existent deja en base
    doublons = conn.execute("""
        SELECT signature_dedup, COUNT(*) as n
        FROM annales_externes
        WHERE etablissement IS NOT NULL AND etablissement != ''
        GROUP BY signature_dedup
        HAVING n > 1
        ORDER BY n DESC
    """).fetchall()

    print(f"\n{len(rows)} lignes mises a jour avec leur signature.")
    print(f"{len(doublons)} signatures dupliquees detectees (meme devoir, sources differentes probablement) :")
    for d in doublons[:20]:
        print(f"  {d['signature_dedup']} -> {d['n']} occurrences")

    conn.close()


if __name__ == '__main__':
    migrer()