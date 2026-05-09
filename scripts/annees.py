ANNEES_DISPONIBLES = {
    'BEPC' : {
        'Mathematiques': [2020, 2021, 2022, 2023, 2024, 2025],
        'PCT' : [2020, 2021, 2022, 2023, 2024, 2025],
     },
    'BAC' : {
        'C' : {
             'Mathematiques' : [2020, 2021, 2022],
             'Physique' : [2020, 2021, 2022, 2023, 2024, 2025],
        },
        'D' : {
            'SVT' : [2020, 2021, 2022, 2023, 2024, 2025],
            'Mathematiques' : [2020, 2021, 2022, 2023, 2024, 2025],
        }
        
    },
}
def afficher_annees(niveau, matiere, serie=None):
    if niveau not in ANNEES_DISPONIBLES:
        print('niveau inconnu')
        return
    if niveau == 'BEPC':
        annees = ANNEES_DISPONIBLES['BEPC'][matiere]
    else:
        annees = ANNEES_DISPONIBLES[niveau][serie][matiere]
    for annee in annees:
        print(f'  -{annee}')
afficher_annees('BEPC', 'PCT')
afficher_annees('BAC', 'SVT', 'D')