# scripts/valider_epreuve.py
"""
Validation du contenu généré par Gemini, AVANT écriture du fichier
JSON final -- point d'insertion identifié lors de la revue du
22/08/2026 pour éviter que des failles connues n'atteignent le PDF
livré à un prof :

  1. LaTeX hors du sous-ensemble supporté par matplotlib.mathtext
     (matrices, \\pmod, \\left/\\right) -> fuite de LaTeX brut dans le PDF
  2. LaTeX écrit hors des signes $...$ (backslash non encadré)
  3. Barème incohérent (sous-questions qui ne totalisent pas le
     barème de l'exercice/partie, ou total général != 20)
  4. Méta-commentaire du modèle qui fuite dans le contenu livré
     (ex: "Correction contextuelle : ajustons la valeur cible...")
  5. (EXTENSION du 26/08/2026) Question réservée à une série (C ou E)
     incompatible avec la série demandée pour un Examen officiel --
     voir detecter_serie_incorrecte() ci-dessous.

Ce module ne CORRIGE rien -- il détecte et fait échouer la validation
pour déclencher une nouvelle tentative de génération (voir
generer_epreuve_json.py). Réparer automatiquement un LaTeX cassé ou un
barème faux serait un nouveau pansement du même genre que l'ancienne
reparer_echappements_latex() -- mieux vaut régénérer proprement.
"""

import re


# Sous-ensemble LaTeX INTERDIT car non supporté par matplotlib.mathtext
# (moteur de rendu dans construire_pdf_officiel.py). Toute occurrence
# dans un champ texte du JSON déclenche un rejet de la génération.
PATTERNS_LATEX_INTERDITS = {
    r"\\begin\{": "environnement LaTeX (\\begin{...}) -- matrices/cases non supportées par le renderer",
    r"\\end\{": "environnement LaTeX (\\end{...})",
    r"\\left": "\\left -- délimiteurs auto non supportés, utiliser ( ) [ ] simples",
    r"\\right": "\\right -- délimiteurs auto non supportés",
    r"\\pmod": "\\pmod -- non supporté, doit être écrit '(mod n)' en texte normal",
    r"\\substack": "\\substack -- non supporté",
    r"\\array\b": "\\array -- non supporté",
}

# Marqueurs de méta-commentaire du modèle qui n'ont RIEN à faire dans
# un contenu livré à un prof -- liste construite à partir des fuites
# réellement observées dans l'audit du 22/08/2026.
MARQUEURS_FUITE_META = [
    "correction contextuelle",
    "ajustons",
    "note contextuelle",
    "en tant qu'ia",
    "en tant que modèle",
    "je ne peux pas générer",
    "nous supposons que l'énoncé",
    "gardons la structure",
    "(note :",
    "(note:",
]

TOLERANCE_BAREME = 0.05  # marge d'arrondi flottant acceptée

# Motif détectant une commande LaTeX (\frac, \theta, \equiv, \in, \infty,
# \mathbb, etc.) qui apparaît EN DEHORS d'un segment $...$ -- signe que
# Gemini a écrit du LaTeX sans l'encadrer par des signes dollar, malgré
# la consigne. C'est un bug différent du \pmod (détecté même À
# L'INTÉRIEUR d'un $...$) : ici on cherche du LaTeX qui a fuité en
# texte normal, backslash compris.
MOTIF_LATEX_NON_ENCADRE = re.compile(r'\\[a-zA-Z]+')


def _tous_les_textes(contenu: dict):
    """Générateur qui parcourt tous les champs texte du contenu généré
    -- un seul point de passage pour les contrôles de contenu, pour ne
    pas dupliquer la logique de parcours de la structure à chaque fois
    qu'on ajoute un contrôle."""
    for partie in contenu.get("parties", []):
        if partie.get("situation_contexte"):
            yield "partie_competences.situation_contexte", partie["situation_contexte"]

        for exercice in partie.get("exercices") or []:
            titre_ex = exercice.get("titre", "exercice_sans_titre")
            if exercice.get("enonce_intro"):
                yield f"{titre_ex}.enonce_intro", exercice["enonce_intro"]
            for q in exercice.get("questions") or []:
                yield f"{titre_ex}.{q.get('numero')}", q.get("texte", "")

        for t in partie.get("taches") or []:
            yield f"partie_competences.{t.get('numero')}", t.get("texte", "")


def detecter_latex_interdit(contenu: dict) -> list[str]:
    problemes = []
    for emplacement, texte in _tous_les_textes(contenu):
        if not texte:
            continue
        for motif, raison in PATTERNS_LATEX_INTERDITS.items():
            if re.search(motif, texte):
                extrait = texte[:80].replace("\n", " ")
                problemes.append(f"[{emplacement}] {raison} -- extrait : \"{extrait}...\"")
    return problemes


def detecter_latex_non_encadre(contenu: dict) -> list[str]:
    problemes = []
    for emplacement, texte in _tous_les_textes(contenu):
        if not texte:
            continue
        # On retire d'abord tous les segments $...$ correctement encadrés
        # -- tout backslash restant en dehors est forcément une fuite.
        texte_hors_dollars = re.sub(r'\$[^$]+\$', '', texte)
        occurrences = MOTIF_LATEX_NON_ENCADRE.findall(texte_hors_dollars)
        if occurrences:
            extrait = texte[:100].replace("\n", " ")
            problemes.append(
                f"[{emplacement}] LaTeX non encadré par $...$ détecté ({occurrences[:3]}) "
                f"-- extrait : \"{extrait}...\""
            )
    return problemes


def detecter_fuite_meta(contenu: dict) -> list[str]:
    problemes = []
    for emplacement, texte in _tous_les_textes(contenu):
        if not texte:
            continue
        texte_bas = texte.lower()
        for marqueur in MARQUEURS_FUITE_META:
            if marqueur in texte_bas:
                problemes.append(f"[{emplacement}] marqueur de fuite détecté : \"{marqueur}\"")
    return problemes


def valider_baremes(contenu: dict) -> list[str]:
    problemes = []
    total_general = 0.0

    for partie in contenu.get("parties", []):
        bareme_partie_annonce = partie.get("bareme_points") or 0
        total_general += bareme_partie_annonce

        if partie.get("type_partie") == "ressources":
            somme_exercices = 0.0
            for exercice in partie.get("exercices") or []:
                titre_ex = exercice.get("titre", "exercice_sans_titre")
                bareme_ex_annonce = exercice.get("bareme_points") or 0
                somme_exercices += bareme_ex_annonce

                somme_questions = sum((q.get("bareme") or 0) for q in exercice.get("questions") or [])
                if abs(somme_questions - bareme_ex_annonce) > TOLERANCE_BAREME:
                    problemes.append(
                        f"[{titre_ex}] somme des sous-questions ({somme_questions}) "
                        f"!= barème annoncé de l'exercice ({bareme_ex_annonce})"
                    )

                for q in exercice.get("questions") or []:
                    if (q.get("bareme") or 0) > 1.5:
                        problemes.append(
                            f"[{titre_ex}.{q.get('numero')}] barème de {q.get('bareme')} pt > 1.5 pt "
                            f"-- sous-question probablement pas assez découpée"
                        )

            if abs(somme_exercices - bareme_partie_annonce) > TOLERANCE_BAREME:
                problemes.append(
                    f"[Partie Ressources] somme des exercices ({somme_exercices}) "
                    f"!= barème annoncé de la partie ({bareme_partie_annonce})"
                )

        elif partie.get("type_partie") == "competences":
            somme_taches = sum((t.get("bareme") or 0) for t in partie.get("taches") or [])
            if abs(somme_taches - bareme_partie_annonce) > TOLERANCE_BAREME:
                problemes.append(
                    f"[Partie Compétences] somme des tâches ({somme_taches}) "
                    f"!= barème annoncé de la partie ({bareme_partie_annonce})"
                )

    total_general += contenu.get("presentation_points") or 0
    if abs(total_general - 20) > TOLERANCE_BAREME:
        problemes.append(f"Barème total de l'épreuve = {total_general} pts (attendu : 20)")

    return problemes


def detecter_serie_incorrecte(contenu: dict, serie_demandee: str) -> list[str]:
    """Uniquement pertinent pour un Examen officiel (Bac), où certaines
    questions peuvent être réservées à une série précise (ex: une
    question de spécialité propre à la série C, absente en série E --
    voir les sujets 2020/2021 qui contiennent des blocs 'Série C
    uniquement' / 'Série E uniquement').

    Rejette toute question dont serie_applicable ne correspond ni à
    la série demandée par le prof, ni à 'toutes' -- ex: si le prof
    demande une épreuve Série E et que Gemini a quand même inclus une
    question marquée serie_applicable='C', c'est une violation directe
    du format officiel MINESEC, pas une variante de style acceptable.

    N'est appelé par valider_epreuve_generee() que si serie_demandee
    est fourni (donc jamais pour une épreuve de séquence, où la notion
    de série n'existe pas)."""
    problemes = []
    for partie in contenu.get("parties", []):
        for exercice in partie.get("exercices") or []:
            titre_ex = exercice.get("titre", "exercice_sans_titre")
            for q in exercice.get("questions") or []:
                serie_q = q.get("serie_applicable", "toutes")
                if serie_q not in ("toutes", serie_demandee):
                    problemes.append(
                        f"[{titre_ex}.{q.get('numero')}] serie_applicable='{serie_q}' "
                        f"incompatible avec la série demandée ('{serie_demandee}') -- "
                        f"cette question ne devrait pas apparaître dans cette épreuve"
                    )
    return problemes


def valider_epreuve_generee(contenu: dict, serie_demandee: str | None = None) -> tuple[bool, list[str]]:
    """Point d'entrée unique, appelé depuis generer_epreuve_json.py
    juste après le parsing JSON, avant l'écriture du fichier.

    `serie_demandee` : uniquement fourni pour un Examen officiel
    (type_document='Examen') -- déclenche le contrôle supplémentaire
    detecter_serie_incorrecte(). Reste None pour une épreuve de
    séquence normale, où la notion de série n'existe pas -- dans ce
    cas ce contrôle est entièrement absent, comportement identique à
    avant cette extension.

    Retourne (ok, liste_des_problemes). ok=False si AU MOINS un
    problème est détecté, dans n'importe laquelle des catégories --
    l'appelant doit alors redéclencher une génération plutôt qu'écrire
    ce contenu."""
    problemes = []
    problemes += detecter_latex_interdit(contenu)
    problemes += detecter_latex_non_encadre(contenu)
    problemes += detecter_fuite_meta(contenu)
    problemes += valider_baremes(contenu)
    if serie_demandee:
        problemes += detecter_serie_incorrecte(contenu, serie_demandee)
    return (len(problemes) == 0, problemes)