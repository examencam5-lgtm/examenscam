# matieres.py

# matiere.py
# Catalogue officiel des matières par niveau et série
# Source : programme MINESEC Cameroun
# Ce fichier = la connaissance pédagogique du projet
# Il sert de référence et de fallback quand la BDD est vide

# ══════════════════════════════════════════════════════
# CATALOGUE OFFICIEL
# ══════════════════════════════════════════════════════

MATIERES = {
    'BEPC': {
        'matieres': [
            'Mathematiques',
            'PCT',
            'SVT',
            'Français',
            'Anglais',
            'Histoire-Géo',
            'Education Civique',
        ],
        'coefficients': {
            'Mathematiques': 4,
            'PCT': 3,
            'SVT': 2,
            'Français': 4,
            'Anglais': 3,
            'Histoire-Géo': 2,
            'Education Civique':1,
        }
    },

    'Probatoire': {
        'C': {
            'matieres': ['Mathematiques', 'PCT', 'Philosophie', 'Français', 'Anglais'],
            'coefficients': {
                'Mathematiques': 5,
                'PCT': 4,
                'Philosophie': 3,
                'Français': 3,
                'Anglais': 2,
            }
        },
        'D': {
            'matieres': ['Mathematiques', 'PCT', 'SVT', 'Philosophie', 'Français', 'Anglais'],
            'coefficients': {
                'Mathematiques': 4,
                'PCT': 3,
                'SVT': 4,
                'Philosophie': 3,
                'Français': 3,
                'Anglais': 2,
            }
        },
        'TI': {
            'matieres': ['Mathematiques', 'PCT', 'Informatique', 'Philosophie', 'Français', 'Anglais'],
            'coefficients': {
                'Mathematiques': 4,
                'PCT': 4,
                'Informatique': 4,
                'Philosophie': 2,
                'Français': 2,
                'Anglais': 2,
            }
        },
        'A4': {
            'matieres': ['Philosophie', 'Français', 'Anglais', 'Histoire-Géo'],
            'coefficients': {
                'Philosophie': 5,
                'Français': 5,
                'Anglais': 4,
                'Histoire-Géo':3,
            }
        },
    },

    'BAC': {
        'C': {
            'matieres': ['Mathematiques', 'PCT', 'SVT', 'Philosophie', 'Français', 'Anglais'],
            'coefficients': {
                'Mathematiques': 7,
                'PCT': 6,
                'SVT': 2,
                'Philosophie': 3,
                'Français': 3,
                'Anglais': 2,
            }
        },
        'D': {
            'matieres': ['Mathematiques', 'PCT', 'SVT', 'Philosophie', 'Français', 'Anglais'],
            'coefficients': {
                'Mathematiques': 4,
                'PCT': 4,
                'SVT': 5,
                'Philosophie': 3,
                'Français': 3,
                'Anglais': 2,
            }
        },
        'TI': {
            'matieres': ['Mathematiques', 'PCT', 'Informatique', 'Philosophie', 'Français', 'Anglais'],
            'coefficients': {
                'Mathematiques': 5,
                'PCT': 5,
                'Informatique': 4,
                'Philosophie': 2,
                'Français': 2,
                'Anglais': 2,
            }
        },
        'A4': {
            'matieres': ['Philosophie', 'Français', 'Anglais', 'Histoire-Géo'],
            'coefficients': {
                'Philosophie': 6,
                'Français': 5,
                'Anglais': 4,
                'Histoire-Géo':3,
            }
        },
    },
}


# ══════════════════════════════════════════════════════
# FONCTIONS UTILES
# ══════════════════════════════════════════════════════

def get_matieres_catalogue(niveau: str, serie: str = None) -> list:
    """
    Retourne la liste officielle des matières depuis le catalogue.
    Utilisé comme fallback si la base de données est vide.

    Exemples :
        get_matieres_catalogue('BEPC') → ['Mathematiques', 'PCT', ...]
        get_matieres_catalogue('BAC', 'C') → ['Mathematiques', 'PCT', ...]
        get_matieres_catalogue('Probatoire', 'D') → ['SVT', ...]
    """
    try:
        if niveau == 'BEPC':
            return MATIERES['BEPC']['matieres']

        if niveau in ('BAC', 'Probatoire') and serie:
            return MATIERES[niveau][serie]['matieres']

        # Toutes les matières du niveau (toutes séries confondues)
        if niveau in ('BAC', 'Probatoire'):
            toutes = set()
            for s in MATIERES[niveau].values():
                toutes.update(s['matieres'])
            return sorted(toutes)

    except KeyError:
        pass

    return []


def get_coefficient(niveau: str, matiere: str, serie: str = None) -> int:
    """
    Retourne le coefficient officiel d'une matière.
    Utile pour trier les matières par importance dans l'interface.

    Exemple :
        get_coefficient('BAC', 'Mathematiques', 'C') → 7
        get_coefficient('BEPC', 'Français') → 4
    """
    try:
        if niveau == 'BEPC':
            return MATIERES['BEPC']['coefficients'].get(matiere, 1)

        if niveau in ('BAC', 'Probatoire') and serie:
            return MATIERES[niveau][serie]['coefficients'].get(matiere, 1)

    except KeyError:
        pass

    return 1


def valider_combinaison(niveau: str, serie: str = None, matiere: str = None) -> bool:
    """
    Vérifie qu'une combinaison niveau/série/matière est valide
    selon le programme officiel.

    Utilisé dans les routes Flask pour rejeter les URL invalides.

    Exemples :
        valider_combinaison('BAC', 'C', 'SVT') → True
        valider_combinaison('BEPC', None, 'PCT') → True
        valider_combinaison('BAC', 'Z', 'Maths') → False (série Z inexistante)
    """
    try:
        if niveau == 'BEPC':
            if matiere:
                return matiere in MATIERES['BEPC']['matieres']
            return True

        if niveau in ('BAC', 'Probatoire'):
            if serie not in MATIERES[niveau]:
                return False
            if matiere:
                return matiere in MATIERES[niveau][serie]['matieres']
            return True

    except KeyError:
        pass

    return False


def matieres_par_coefficient(niveau: str, serie: str = None) -> list:
    """
    Retourne les matières triées par coefficient décroissant.
    Les matières importantes apparaissent en premier dans l'interface.

    Exemple :
        matieres_par_coefficient('BAC', 'C')
        → ['Mathematiques' (7), 'PCT' (6), 'Philosophie' (3), ...]
    """
    matieres = get_matieres_catalogue(niveau, serie)

    return sorted(
        matieres,
        key=lambda m: get_coefficient(niveau, m, serie),
        reverse=True
    )


def get_series_disponibles(niveau: str) -> list:
    """
    Retourne les séries disponibles pour un niveau.

    Exemple :
        get_series_disponibles('BAC') → ['C', 'D', 'TI', 'A4']
    """
    if niveau in ('BAC', 'Probatoire'):
        return list(MATIERES[niveau].keys())
    return []


# ══════════════════════════════════════════════════════
# AFFICHAGE — Pour vérification en terminal
# ══════════════════════════════════════════════════════

def afficher_catalogue():
    """Affiche le catalogue complet dans le terminal."""
    for niveau in ['BEPC', 'Probatoire', 'BAC']:
        print(f"\n{'═'*40}")
        print(f" {niveau}")
        print(f"{'═'*40}")

        if niveau == 'BEPC':
            for m in matieres_par_coefficient('BEPC'):
                coef = get_coefficient('BEPC', m)
                print(f" coef {coef} — {m}")
        else:
            for serie in get_series_disponibles(niveau):
                print(f"\n Série {serie} :")
                for m in matieres_par_coefficient(niveau, serie):
                    coef = get_coefficient(niveau, m, serie)
                    print(f" coef {coef} — {m}")


if __name__ == "__main__":
    afficher_catalogue()

