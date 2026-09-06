# scripts/ajouter_credits_manuel.py
"""
Ajout manuel de crédits à un élève -- solution TEMPORAIRE pendant que
CinetPay/Flutterwave ne sont pas encore intégrés (voir database_credits.py,
en-tête du fichier : Monetbil ne répond plus, Flutterwave a refusé).

USAGE (depuis la racine du projet, environnement virtuel activé si tu
en utilises un) :

    python scripts/ajouter_credits_manuel.py <eleve_id> <nombre_credits> [reference]

Exemple concret : un élève te paie 500 FCFA en MTN MoMo directement,
hors plateforme (comme c'est le cas aujourd'hui). Au tarif actuel
(1 crédit = 1 FCFA, voir PRIX_CREDIT_FCFA dans database_credits.py),
ça correspond à 500 crédits :

    python scripts/ajouter_credits_manuel.py 42 500 "MTN MoMo manuel 06/09/2026"

Le 3e argument (reference) est optionnel mais RECOMMANDÉ -- il est
stocké dans transactions_credits.payment_ref, et c'est la seule trace
qui te permettra plus tard de retrouver quel paiement réel correspond
à quel ajout de crédits, si jamais une question de litige se pose
(élève qui prétend avoir payé plus, erreur de saisie de ta part, etc.).

CE SCRIPT NE VÉRIFIE PAS QUE LE PAIEMENT A RÉELLEMENT EU LIEU -- c'est
TOI qui portes cette responsabilité en le lançant (voir la docstring
de ajouter_credits_achetes() dans database_credits.py : "à appeler
une fois un paiement CONFIRMÉ, jamais avant"). Ne lance ce script
qu'après avoir personnellement vérifié la réception du paiement
(SMS MTN/Orange, capture d'écran de l'élève, etc.).

TROUVER L'ID D'UN ÉLÈVE : si tu ne connais que son nom ou son
numéro/email, cherche-le d'abord dans Neon SQL Editor :

    SELECT id, nom, email, telephone FROM eleves WHERE nom ILIKE '%dupont%';

(adapte le nom de la colonne de recherche selon ce qu'affiche
réellement ta table eleves -- ILIKE fait une recherche insensible à
la casse en Postgres).
"""

import sys

if __package__:
    from . import database_credits
else:
    import database_credits


def main():
    if len(sys.argv) < 3:
        print(
            "Usage : python scripts/ajouter_credits_manuel.py "
            "<eleve_id> <nombre_credits> [reference]"
        )
        sys.exit(1)

    try:
        eleve_id = int(sys.argv[1])
    except ValueError:
        print(f"Erreur : eleve_id doit être un nombre entier, reçu : {sys.argv[1]!r}")
        sys.exit(1)

    try:
        nombre_credits = int(sys.argv[2])
    except ValueError:
        print(f"Erreur : nombre_credits doit être un nombre entier, reçu : {sys.argv[2]!r}")
        sys.exit(1)

    reference = sys.argv[3] if len(sys.argv) > 3 else None

    # Affiche le solde AVANT, pour permettre une vérification visuelle
    # immédiate -- utile si tu lances ce script en direct pendant que
    # l'élève attend la confirmation.
    solde_avant = database_credits.get_solde(eleve_id)
    print(f"Solde AVANT (élève {eleve_id}) : {solde_avant['total']} crédits "
          f"({solde_avant['credits_gratuits_restants']} gratuits + "
          f"{solde_avant['credits_payants']} payants)")

    prix_fcfa = database_credits.prix_fcfa_pour_credits(nombre_credits)
    print(f"\nAjout de {nombre_credits} crédits "
          f"(valeur de vente : {prix_fcfa} FCFA)"
          + (f", référence : {reference}" if reference else " (sans référence)"))

    confirmation = input("\nConfirmer l'ajout ? (o/n) : ").strip().lower()
    if confirmation != "o":
        print("Annulé -- aucun crédit ajouté.")
        sys.exit(0)

    resultat = database_credits.ajouter_credits_achetes(eleve_id, nombre_credits, reference)

    if not resultat["ok"]:
        print(f"\nÉCHEC : {resultat.get('erreur', 'erreur inconnue')}")
        sys.exit(1)

    print(f"\nOK -- nouveau solde total : {resultat['solde_apres']} crédits.")


if __name__ == "__main__":
    main()