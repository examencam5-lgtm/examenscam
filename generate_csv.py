# generate_csv.py
# ═══════════════════════════════════════════════════════
# Génère TOUS les CSV d'ExamensCam automatiquement
# Physique + Chimie séparés · Examens blancs · Années max
#
# Usage : python generate_csv.py
# ═══════════════════════════════════════════════════════

import csv
from pathlib import Path
from itertools import product

ANNEES_OFFICIELLES = list(range(1990, 2025)) # 35 ans
ANNEES_BLANCS = list(range(2010, 2025)) # 15 ans
DOSSIER_SORTIE = Path('csv_examenscam')

COLONNES = ['niveau', 'serie', 'matiere', 'annee',
            'lien_drive', 'corrige_dispo', 'source', 'type']

CATALOGUE = {

    'BEPC_NA': {
        'niveau': 'BEPC', 'serie': '', 'type': 'officiel',
        'matieres': ['Mathematiques', 'Physique', 'Chimie', 'SVT',
                     'Français', 'Anglais', 'Histoire-Géo', 'Education Civique'],
    },

    'Probatoire_C': {
        'niveau': 'Probatoire', 'serie': 'C', 'type': 'officiel',
        'matieres': ['Mathematiques', 'Physique', 'Chimie',
                     'Philosophie', 'Français', 'Anglais'],
    },
    'Probatoire_D': {
        'niveau': 'Probatoire', 'serie': 'D', 'type': 'officiel',
        'matieres': ['Mathematiques', 'Physique', 'Chimie', 'SVT',
                     'Philosophie', 'Français', 'Anglais'],
    },
    'Probatoire_TI': {
        'niveau': 'Probatoire', 'serie': 'TI', 'type': 'officiel',
        'matieres': ['Mathematiques', 'Physique', 'Chimie', 'Informatique',
                     'Philosophie', 'Français', 'Anglais'],
    },
    'Probatoire_A4': {
        'niveau': 'Probatoire', 'serie': 'A4', 'type': 'officiel',
        'matieres': ['Philosophie', 'Français', 'Anglais',
                     'Histoire-Géo', 'Latin'],
    },

    'ProbBlanc_C': {
        'niveau': 'Probatoire Blanc', 'serie': 'C', 'type': 'blanc',
        'matieres': ['Mathematiques', 'Physique', 'Chimie',
                     'Philosophie', 'Français', 'Anglais'],
    },
    'ProbBlanc_D': {
        'niveau': 'Probatoire Blanc', 'serie': 'D', 'type': 'blanc',
        'matieres': ['Mathematiques', 'Physique', 'Chimie', 'SVT',
                     'Philosophie', 'Français', 'Anglais'],
    },
    'ProbBlanc_TI': {
        'niveau': 'Probatoire Blanc', 'serie': 'TI', 'type': 'blanc',
        'matieres': ['Mathematiques', 'Physique', 'Chimie', 'Informatique',
                     'Français', 'Anglais'],
    },
    'ProbBlanc_A4': {
        'niveau': 'Probatoire Blanc', 'serie': 'A4', 'type': 'blanc',
        'matieres': ['Philosophie', 'Français', 'Anglais', 'Histoire-Géo'],
    },

    'BAC_C': {
        'niveau': 'BAC', 'serie': 'C', 'type': 'officiel',
        'matieres': ['Mathematiques', 'Physique', 'Chimie', 'SVT',
                     'Philosophie', 'Français', 'Anglais'],
    },
    'BAC_D': {
        'niveau': 'BAC', 'serie': 'D', 'type': 'officiel',
        'matieres': ['Mathematiques', 'Physique', 'Chimie', 'SVT',
                     'Philosophie', 'Français', 'Anglais'],
    },
    'BAC_TI': {
        'niveau': 'BAC', 'serie': 'TI', 'type': 'officiel',
        'matieres': ['Mathematiques', 'Physique', 'Chimie', 'Informatique',
                     'Dessin Industriel', 'Philosophie', 'Français', 'Anglais'],
    },
    'BAC_A4': {
        'niveau': 'BAC', 'serie': 'A4', 'type': 'officiel',
        'matieres': ['Philosophie', 'Français', 'Anglais',
                     'Histoire-Géo', 'Latin', 'Economie'],
    },

    'BACBlanc_C': {
        'niveau': 'BAC Blanc', 'serie': 'C', 'type': 'blanc',
        'matieres': ['Mathematiques', 'Physique', 'Chimie', 'SVT',
                     'Philosophie', 'Français', 'Anglais'],
    },
    'BACBlanc_D': {
        'niveau': 'BAC Blanc', 'serie': 'D', 'type': 'blanc',
        'matieres': ['Mathematiques', 'Physique', 'Chimie', 'SVT',
                     'Philosophie', 'Français', 'Anglais'],
    },
    'BACBlanc_TI': {
        'niveau': 'BAC Blanc', 'serie': 'TI', 'type': 'blanc',
        'matieres': ['Mathematiques', 'Physique', 'Chimie', 'Informatique',
                     'Français', 'Anglais'],
    },
    'BACBlanc_A4': {
        'niveau': 'BAC Blanc', 'serie': 'A4', 'type': 'blanc',
        'matieres': ['Philosophie', 'Français', 'Anglais', 'Histoire-Géo'],
    },
}


def generer_fichier(cle, groupe):
    annees = ANNEES_BLANCS if groupe['type'] == 'blanc' else ANNEES_OFFICIELLES
    lignes = []

    for matiere, annee in product(groupe['matieres'], annees):
        lignes.append({
            'niveau': groupe['niveau'],
            'serie': groupe['serie'],
            'matiere': matiere,
            'annee': annee,
            'lien_drive': '',
            'corrige_dispo': '0',
            'source': '',
            'type': groupe['type'],
        })

    lignes.sort(key=lambda x: (x['matiere'], -x['annee']))

    chemin = DOSSIER_SORTIE / f"{cle}.csv"
    with open(chemin, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=COLONNES)
        writer.writeheader()
        writer.writerows(lignes)

    print(f" ✅ {cle:<30} {len(lignes):>4} lignes "
          f"({len(groupe['matieres'])} matières × {len(annees)} années)")
    return len(lignes)


def generer_tout():
    DOSSIER_SORTIE.mkdir(exist_ok=True)

    print("\n" + "═"*58)
    print(" ExamensCam — Génération CSV complète")
    print("═"*58 + "\n")

    sections = {
        'BEPC': ['BEPC_NA'],
        'Probatoire officiel': ['Probatoire_C','Probatoire_D',
                                'Probatoire_TI','Probatoire_A4'],
        'Probatoire blanc': ['ProbBlanc_C','ProbBlanc_D',
                                'ProbBlanc_TI','ProbBlanc_A4'],
        'BAC officiel': ['BAC_C','BAC_D','BAC_TI','BAC_A4'],
        'BAC blanc': ['BACBlanc_C','BACBlanc_D',
                                'BACBlanc_TI','BACBlanc_A4'],
    }

    total = 0
    nb_fichiers = 0

    for section, cles in sections.items():
        print(f"── {section}")
        for cle in cles:
            total += generer_fichier(cle, CATALOGUE[cle])
            nb_fichiers += 1
        print()

    print("═"*58)
    print(f" {nb_fichiers} fichiers → dossier /{DOSSIER_SORTIE}/")
    print(f" {total:,} lignes au total")
    print("═"*58)
    print(f"""
📋 Mode d'emploi :
  1. Ouvre un CSV dans Excel/WPS
  2. Données → Convertir → Délimité → Virgule
  3. Colle les liens Drive dans la colonne lien_drive
  4. Supprime les lignes sans lien
  5. Sauvegarde en CSV et uploade dans l'admin
""")


if __name__ == '__main__':
    generer_tout()

