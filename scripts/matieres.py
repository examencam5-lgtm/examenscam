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
        'A4' : ['Literature', 'Langue', 'Anglais', ]
    },
}
print(MATIERES['BEPC'])
print(MATIERES['BAC']['C'])
