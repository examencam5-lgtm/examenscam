"""
extracteur_matiere.py — ExamensCam
Detecte la matiere depuis un titre d'epreuve scrapee, quand le
scraper ne l'a pas capturee comme colonne separee (cas
epreuvesetcorriges, qui n'expose pas la matiere dans sa structure
de categories -- contrairement a sujetexa dont les sous-categories
EN SONT la matiere directement).

Priorite : motifs les plus specifiques d'abord (ex: 'svteehb' avant
'svt' seul, sinon 'svt' matcherait a tort dans 'svteehb').
"""
import re
import unicodedata


def normaliser(texte: str) -> str:
    if not texte:
        return ""
    texte = texte.lower()
    texte = unicodedata.normalize('NFKD', texte)
    texte = ''.join(c for c in texte if not unicodedata.combining(c))
    return texte


# (motif_normalise, matiere_canonique) -- ORDRE IMPORTANT, du plus
# specifique au plus generique
MOTIFS_MATIERE = [
    (r"svteehb", "SVTEEHB"),
    (r"sciences? de la vie et de la terre|\bsvt\b", "SVT"),
    (r"sciences? economiques? et juridiques?", "Sciences Économiques et Juridiques"),
    (r"sciences? economiques? et sociales? et familiales?", "ESF"),
    (r"physique.{0,15}chimie|\bpct\b", "PCT"),
    (r"expression ecrite|dissertation|contraction de texte|orthographe|langue francaise|\bfrancais\b", "Francais"),
    (r"etude de texte", "Francais"),
    (r"litterature", "Litterature"),
    (r"culture generale", "Culture Generale"),
    (r"dessin", "Dessin d'Art"),
    (r"travail manuel", "Travail Manuel"),
    (r"informatique|algorithmique et programmation|systeme d.information", "Informatique"),
    (r"mathematiques?|\bmaths\b", "Mathematiques"),
    (r"\bchimie\b", "Chimie"),
    (r"\bphysique\b", "Physique"),
    (r"\bhistoire\b", "Histoire"),
    (r"geographie", "Geographie"),
    (r"philosophie", "Philosophie"),
    (r"\banglais\b", "Anglais"),
    (r"\ballemand\b", "Allemand"),
    (r"\bespagnol\b", "Espagnol"),
    (r"\bitalien\b", "Italien"),
    (r"\bchinois\b", "Chinois"),
    (r"\barabe\b", "Arabe"),
    (r"\beps\b|education physique", "EPS"),
    (r"comptabilite", "Comptabilite"),
    (r"\becm\b|education civique|education a la citoyennete", "ECM"),
]


def detecter_matiere(titre: str) -> str | None:
    titre_norm = normaliser(titre)
    for motif, canonique in MOTIFS_MATIERE:
        if re.search(motif, titre_norm):
            return canonique
    return None


if __name__ == "__main__":
    import csv
    from collections import Counter

    with open('/mnt/user-data/uploads/epreuvesetcorriges_brut.csv', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    detectees = Counter()
    non_detectees = []

    for r in rows:
        m = detecter_matiere(r['titre'])
        if m:
            detectees[m] += 1
        else:
            non_detectees.append(r['titre'])

    print(f"Total lignes : {len(rows)}")
    print(f"Matiere detectee : {sum(detectees.values())} ({100*sum(detectees.values())/len(rows):.1f}%)")
    print(f"Non detectee : {len(non_detectees)}")
    print()
    print("Repartition des matieres detectees :")
    for m, n in detectees.most_common():
        print(f"  {m:35s} {n}")
    print()
    print("--- 20 titres NON detectes (echantillon) ---")
    for t in non_detectees[:20]:
        print(f"  {t[:90]}") 