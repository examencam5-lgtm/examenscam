# scripts/matieres.py
#dictionnaire de matieres par niveaux et series

MATIERES = {
    'BEPC' : ['Mathematiques', 'SVT', 'PCT', 'Anglais', 'Informatique'],
    'PROBATOIRE' : {
        'C' : ['Mathematiques', 'Physique', 'Chimie', 'Informatique'],
        'D' : ['SVT', 'Mathematiques', 'Physique', 'Chimie', 'Informatique'],
        'A4' : ['Literature', 'Anglais', 'Langue',],
    },
    'BAC' : {
        'C' : ['Mathematiques', 'Physique', 'Chimie', 'Informatique'],
        'D' : ['SVT', 'Mathematiques', 'Physique', 'Chimie', 'Informatique'],
        'A4' : ['Literature', 'Langue', 'Anglais', ],
}
}
def afficher_matieres(niveau,serie=None):
    if niveau == 'BEPC':
        print(f"\nBEPC - Matieres:")
        for matiere in MATIERES['BEPC']:
            print(f"  -{matiere}")
    else:
        if serie:
            print(f"\n{niveau} Serie {serie}  -Matieres :")
            for matiere in MATIERES[niveau][serie]:
                print(f"  -{matiere}")
        else:
            for s, matiere in MATIERES[niveau].items():
                print(f" serie {s} :")
                for matieres in MATIERES[niveau][serie]:
                    print(f"  -{matiere}")
afficher_matieres('BEPC')
afficher_matieres('BAC', 'C')
afficher_matieres('PROBATOIRE', 'D')
afficher_matieres('BAC', 'D')
afficher_matieres('PROBATOIRE', 'A4')
afficher_matieres('BAC', 'A4')