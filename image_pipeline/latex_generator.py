"""
Génère du LaTeX propre à partir d'exercices analysés.
Détecte et formate automatiquement les formules mathématiques.
"""

import re
from pathlib import Path
from typing import Dict, List


# Dictionnaire de conversion texte → LaTeX
CONVERSIONS_MATH = {
    '×': r'\times',
    '÷': r'\div',
    '±': r'\pm',
    '∓': r'\mp',
    '≤': r'\leq',
    '≥': r'\geq',
    '≠': r'\neq',
    '≈': r'\approx',
    '≡': r'\equiv',
    '∞': r'\infty',
    '∈': r'\in',
    '∉': r'\notin',
    '⊂': r'\subset',
    '⊃': r'\supset',
    '∪': r'\cup',
    '∩': r'\cap',
    '∅': r'\emptyset',
    'ℕ': r'\mathbb{N}',
    'ℤ': r'\mathbb{Z}',
    'ℚ': r'\mathbb{Q}',
    'ℝ': r'\mathbb{R}',
    'ℂ': r'\mathbb{C}',
    '∀': r'\forall',
    '∃': r'\exists',
    '⇒': r'\Rightarrow',
    '⇔': r'\Leftrightarrow',
    'α': r'\alpha',
    'β': r'\beta',
    'γ': r'\gamma',
    'δ': r'\delta',
    'ε': r'\epsilon',
    'ζ': r'\zeta',
    'η': r'\eta',
    'θ': r'\theta',
    'ι': r'\iota',
    'κ': r'\kappa',
    'λ': r'\lambda',
    'μ': r'\mu',
    'ν': r'\nu',
    'ξ': r'\xi',
    'π': r'\pi',
    'ρ': r'\rho',
    'σ': r'\sigma',
    'τ': r'\tau',
    'φ': r'\phi',
    'χ': r'\chi',
    'ψ': r'\psi',
    'ω': r'\omega',
    'Γ': r'\Gamma',
    'Δ': r'\Delta',
    'Θ': r'\Theta',
    'Λ': r'\Lambda',
    'Π': r'\Pi',
    'Σ': r'\Sigma',
    'Φ': r'\Phi',
    'Ψ': r'\Psi',
    'Ω': r'\Omega',
    '√': r'\sqrt',
    '∫': r'\int',
    '∑': r'\sum',
    '∏': r'\prod',
    '∂': r'\partial',
    '∇': r'\nabla',
    '→': r'\rightarrow',
    '←': r'\leftarrow',
    '↑': r'\uparrow',
    '↓': r'\downarrow',
    '°': r'^{\circ}',
}


def detecter_formules(texte: str):
    """
    Détecte les zones de formules dans un texte.
    Retourne: liste de (debut, fin, texte_formule)
    """
    formules = []
    
    # Pattern 1: expressions avec = et variables
    pattern_eq = r'([a-zA-Z0-9\s\(\)\[\]\{\}\+\-\*\/\^]+=[a-zA-Z0-9\s\(\)\[\]\{\}\+\-\*\/\^]+)'
    for match in re.finditer(pattern_eq, texte):
        formules.append((match.start(), match.end(), match.group()))
    
    # Pattern 2: expressions avec racines, intégrales, etc.
    pattern_math = r'(√|∫|∑|∏|lim|log|ln|exp|sin|cos|tan|arcsin|arccos|arctan)[^\n]{3,50}'
    for match in re.finditer(pattern_math, texte, re.IGNORECASE):
        chevauche = False
        for f in formules:
            if not (match.end() < f[0] or match.start() > f[1]):
                chevauche = True
                break
        if not chevauche:
            formules.append((match.start(), match.end(), match.group()))
    
    # Pattern 3: expressions entre parenthèses complexes
    pattern_paren = r'\([^\(\)]{5,30}\)'
    for match in re.finditer(pattern_paren, texte):
        chevauche = False
        for f in formules:
            if not (match.end() < f[0] or match.start() > f[1]):
                chevauche = True
                break
        if not chevauche:
            formules.append((match.start(), match.end(), match.group()))
    
    return sorted(formules, key=lambda x: x[0])


def texte_vers_latex_math(texte: str) -> str:
    """
    Convertit un texte contenant des maths en LaTeX.
    """
    for symbole, latex in CONVERSIONS_MATH.items():
        texte = texte.replace(symbole, latex)
    
    # Détecter les exposants (2³, x²)
    texte = re.sub(r'(\w|\))\^?(\d+)', r'\1^{\2}', texte)
    
    # Détecter les fractions simples a/b
    texte = re.sub(r'(\d+)\s*\/\s*(\d+)(?!\d)', r'\\frac{\1}{\2}', texte)
    
    # Détecter les indices (x1, a2)
    texte = re.sub(r'([a-zA-Z])(\d+)(?!\d)', r'\1_{\2}', texte)
    
    return texte


def formater_ligne_latex(ligne: str) -> str:
    """
    Formate une ligne de texte en LaTeX, détectant automatiquement les maths.
    """
    formules = detecter_formules(ligne)
    
    if not formules:
        ligne_latex = texte_vers_latex_math(ligne)
        # Échapper les caractères spéciaux LaTeX
        ligne_latex = ligne_latex.replace('&', r'\&').replace('%', r'\%')
        ligne_latex = ligne_latex.replace('$', r'\$').replace('#', r'\#')
        ligne_latex = ligne_latex.replace('_', r'\_').replace('{', r'\{').replace('}', r'\}')
        return ligne_latex
    
    resultat = []
    pos = 0
    
    for debut, fin, formule in formules:
        if debut > pos:
            texte_avant = ligne[pos:debut]
            texte_avant = texte_vers_latex_math(texte_avant)
            texte_avant = texte_avant.replace('&', r'\&').replace('%', r'\%')
            texte_avant = texte_avant.replace('$', r'\$').replace('#', r'\#')
            resultat.append(texte_avant)
        
        formule_latex = texte_vers_latex_math(formule)
        resultat.append(f'${formule_latex}$')
        
        pos = fin
    
    if pos < len(ligne):
        texte_apres = ligne[pos:]
        texte_apres = texte_vers_latex_math(texte_apres)
        texte_apres = texte_apres.replace('&', r'\&').replace('%', r'\%')
        texte_apres = texte_apres.replace('$', r'\$').replace('#', r'\#')
        resultat.append(texte_apres)
    
    return "".join(resultat)


def generer_latex_exercice(analyse: Dict, numero: int) -> str:
    """
    Génère le code LaTeX complet pour un exercice.
    """
    nom = analyse.get('nom', f'Exercice_{numero}')
    sujet = analyse.get('sujet', 'general')
    contenu = analyse.get('contenu', [])
    
    titre = nom.replace('_', ' ')
    
    titres_sujets = {
        'algebre': 'Algèbre',
        'analyse': 'Analyse',
        'geometrie': 'Géométrie',
        'trigonometrie': 'Trigonométrie',
        'probabilites': 'Probabilités',
        'arithmetique': 'Arithmétique',
        'logique': 'Logique',
        'nombres_complexes': 'Nombres Complexes',
        'fonctions': 'Fonctions',
        'suites': 'Suites',
        'general': 'Mathématiques',
    }
    
    sous_titre = titres_sujets.get(sujet, 'Mathématiques')
    
    corps = []
    for ligne in contenu:
        if not ligne.strip():
            continue
        
        ligne_latex = formater_ligne_latex(ligne)
        
        if re.match(r'^\s*[a-zA-Z][\.\)]\s', ligne):
            corps.append(f'\\item {ligne_latex}')
        elif re.match(r'^\s*\d+[\.\)]\s', ligne):
            corps.append(f'\\item {ligne_latex}')
        else:
            corps.append(ligne_latex + '\\\\')
    
    corps_str = '\n'.join(corps)
    
    latex = f"""% Exercice: {titre}
% Sujet: {sous_titre}
% Généré automatiquement

\\begin{{exercice}}[{sous_titre}]
\\label{{ex:{numero}}}

{corps_str}

\\end{{exercice}}

% --- Fin {titre} ---
"""
    return latex


def generer_document_latex(exercices: List[Dict], titre_doc: str = "Annales de Mathématiques") -> str:
    """
    Génère un document LaTeX complet avec tous les exercices.
    """
    header = r"""\documentclass[12pt,a4paper]{article}

\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[french]{babel}
\usepackage{amsmath,amssymb,amsfonts}
\usepackage{geometry}
\usepackage{enumitem}
\usepackage{xcolor}
\usepackage{hyperref}

\geometry{margin=2.5cm}

\newcounter{exercice}
\newenvironment{exercice}[1][Mathématiques]{%
    \refstepcounter{exercice}%
    \par\medskip\noindent
    \textbf{\large Exercice \theexercice\ -- #1}%
    \par\smallskip
}{%
    \par\medskip
}

\title{""" + titre_doc + r"""}
\author{Annales Probatoire}
\date{\today}

\begin{document}

\maketitle
\tableofcontents
\newpage

"""
    
    corps = []
    for i, ex in enumerate(exercices, 1):
        latex_exo = generer_latex_exercice(ex, i)
        corps.append(latex_exo)
        corps.append('\n\\newpage\n')
    
    footer = r"""
\end{document}
"""
    
    return header + '\n'.join(corps) + footer


def sauver_latex(exercices: List[Dict], output_dir: str, nom_base: str = "exercices"):
    """
    Sauvegarde les exercices en LaTeX (individuel + combiné).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    doc_complet = generer_document_latex(exercices)
    chemin_complet = out_dir / f"{nom_base}_complet.tex"
    with open(chemin_complet, 'w', encoding='utf-8') as f:
        f.write(doc_complet)
    print(f"   📝 LaTeX complet: {chemin_complet.name}")
    
    for i, ex in enumerate(exercices, 1):
        nom = ex.get('nom', f'Exercice_{i}')
        latex_indiv = generer_latex_exercice(ex, i)
        chemin = out_dir / f"{nom}.tex"
        with open(chemin, 'w', encoding='utf-8') as f:
            f.write(latex_indiv)
    
    print(f"   📝 {len(exercices)} fichier(s) LaTeX individuel(s)")
    
    return str(chemin_complet)