"""
classifier_epreuves.py — ExamensCam
Prend un CSV brut de scraping (sujetexa ou epreuvesetcorriges) et le
separe en deux fichiers selon le titre :

  - a_indexer_externe.csv   -> devoirs d'etablissement individuel,
                                indexation + redirection uniquement
                                (table annales_externes)
  - a_heberger_blanche.csv  -> harmonises regionaux / delegations
                                regionales / olympiades / epreuves
                                zero -- Muhammad telecharge et
                                heberge lui-meme (table annales_blanches,
                                doc section 2.2 : meme statut que les
                                officielles, PAS de simple redirection)

Pourquoi cette distinction compte : un harmonise regional emane
d'une delegation regionale MINESEC, c'est un contenu quasi-officiel
que la doc traite comme 'blanche' hebergee -- pas un simple devoir
d'un etablissement prive qu'on se contente d'indexer.

Usage :
    python classifier_epreuves.py epreuvesetcorriges_brut.csv
    python classifier_epreuves.py data/liens_externes/sujetexa_terminale-c_2026.csv
"""
import csv
import re
import sys
from pathlib import Path

# Mots-cles qui signalent un harmonise regional / delegation --
# PAS un devoir d'etablissement individuel. Ordre de specificite :
# ces motifs sont assez caracteristiques du vocabulaire administratif
# MINESEC pour ne pas se confondre avec un titre de devoir de classe.
MOTS_CLES_HARMONISE = [
    r"harmonis[ée]",
    r"d[ée]l[ée]gation r[ée]gionale",
    r"r[ée]gional[e]?\b",
    r"[ée]preuve z[ée]ro",
    r"olympiade",
    r"session (de |d')?(f[ée]vrier|avril|mai|juin)",
    r"bac blanc r[ée]gional",
    r"baccalaur[ée]at blanc r[ée]gional",
]

REGEX_HARMONISE = re.compile("|".join(MOTS_CLES_HARMONISE), re.IGNORECASE)

# Mots-cles qui signalent un etablissement precis (college, lycee,
# institut nommé) -- confirme la classification 'externe' meme si
# un mot-cle harmonise apparait aussi par ailleurs dans le titre
REGEX_ETABLISSEMENT = re.compile(
    r"\b(coll[eè]ge|lyc[ée]e|institut|groupe scolaire|complexe scolaire)\b",
    re.IGNORECASE
)


def classifier_titre(titre: str) -> str:
    """
    Retourne 'blanche' ou 'externe' selon le contenu du titre.

    Regle de priorite : si un nom d'etablissement precis est
    mentionne (Lycee X, College Y), c'est TOUJOURS 'externe' meme
    si le mot 'regional' apparait ailleurs (ex: une delegation
    regionale peut composer un sujet POUR un college precis --
    dans ce cas le devoir reste rattache a l'etablissement).
    Sinon, si un mot-cle harmonise/regional/zero est present ->
    'blanche'. Par defaut (aucun signal clair) -> 'externe', le
    choix le moins engageant (pas d'hebergement automatique).
    """
    if not titre:
        return 'externe'

    if REGEX_ETABLISSEMENT.search(titre):
        return 'externe'

    if REGEX_HARMONISE.search(titre):
        return 'blanche'

    return 'externe'


def classifier_fichier(chemin_csv: str):
    chemin = Path(chemin_csv)
    if not chemin.exists():
        print(f"Fichier introuvable : {chemin_csv}")
        return

    lignes_externe = []
    lignes_blanche = []

    with open(chemin, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for ligne in reader:
            titre = ligne.get('titre', '')
            categorie = classifier_titre(titre)
            if categorie == 'blanche':
                lignes_blanche.append(ligne)
            else:
                lignes_externe.append(ligne)

    dossier_sortie = chemin.parent
    chemin_externe = dossier_sortie / 'a_indexer_externe.csv'
    chemin_blanche = dossier_sortie / 'a_heberger_blanche.csv'

    with open(chemin_externe, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(lignes_externe)

    with open(chemin_blanche, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(lignes_blanche)

    print(f"Classification terminee sur {chemin.name} :")
    print(f"  -> {len(lignes_externe)} lignes 'externe' dans {chemin_externe}")
    print(f"  -> {len(lignes_blanche)} lignes 'blanche' dans {chemin_blanche}")
    print(f"\nPour 'blanche' : telecharge chaque PDF (lien_pdf/lien_externe),")
    print(f"heberge-le sur ton Drive, puis utilise ajouter_epreuve_blanche()")
    print(f"depuis database_blanches.py pour chaque fichier.")
    print(f"\nRelis 'a_indexer_externe.csv' rapidement -- la classification")
    print(f"est heuristique, corrige a la main les cas mal classes avant import.")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage : python classifier_epreuves.py <chemin_csv>")
        sys.exit(1)
    classifier_fichier(sys.argv[1])