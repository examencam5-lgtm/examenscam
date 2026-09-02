# paiement_monetbil.py — ExamensCam
"""
Client HTTP pour l'API Monetbil (paiement Mobile Money) -- UNIQUEMENT
les appels réseau et la logique de signature, jamais de logique
métier (activation d'abonnement, etc., voir database_paiements.py).
Même principe de séparation que gemini_client.py : ce fichier ne
dépend d'aucun autre module du projet, pour rester réutilisable et
facile à tester isolément.

RÉFÉRENCES (documentation officielle vérifiée le 02/09/2026) :
  - Widget v2.1 : https://www.monetbil.com/docs/monetbil-payment-widget-v2.1-en.pdf
  - Notifications : https://www.monetbil.com/docs/monetbil-payment-notification-en.pdf
  - Algorithme de signature : SDK officiel PHP
    (https://github.com/Monetbil/monetbil-php/blob/master/monetbil.php),
    fonctions sign()/checkSign() -- reproduites ici à l'identique en
    Python, aucune improvisation sur ce point : une signature mal
    reproduite rendrait la vérification totalement inutile sans que
    ce soit visible avant une vraie tentative de fraude.

VARIABLES D'ENVIRONNEMENT REQUISES (jamais en dur dans le code, même
principe que SECRET_KEY/ADMIN_TOKEN dans app.py) :
  - MONETBIL_SERVICE_KEY : clé du service, visible sur le tableau de
    bord Monetbil (page du service EXAMENSCAM, celle où on voyait
    "HhTkw4TDyycspfaKWcyqMDIRr8q9FFfO").
  - MONETBIL_SERVICE_SECRET : secret du service, nécessaire UNIQUEMENT
    pour signer les paiements sortants et vérifier les notifications
    entrantes -- généralement affiché à côté de la clé de service,
    parfois sous l'onglet "Développeurs". Si Monetbil ne l'affiche pas
    encore tant que le service n'est pas approuvé, la vérification de
    signature reste désactivée avec un repli explicite (voir
    verifier_signature_notification et son usage dans app.py) plutôt
    que de bloquer les tests.

Nécessite : pip install requests
"""

import hashlib
import hmac
import os
from typing import Optional

import requests

WIDGET_URL = "https://api.monetbil.com/widget/v2.1/{service_key}"
CHECK_PAYMENT_URL = "https://api.monetbil.com/payment/v1/checkPayment"

MONETBIL_SERVICE_KEY_ENV = "MONETBIL_SERVICE_KEY"
MONETBIL_SERVICE_SECRET_ENV = "MONETBIL_SERVICE_SECRET"

TIMEOUT_SEC = 30

# Codes de statut renvoyés par checkPayment -- convention officielle
# Monetbil (voir constantes STATUS_* du SDK PHP). Les valeurs 7/8/9
# sont les équivalents en mode TEST (sandbox) de 1/0/-1 en mode réel.
STATUT_SUCCES = 1
STATUT_ECHEC = 0
STATUT_ANNULE = -1
STATUT_SUCCES_TEST = 7
STATUT_ECHEC_TEST = 8
STATUT_ANNULE_TEST = 9
STATUTS_SUCCES = (STATUT_SUCCES, STATUT_SUCCES_TEST)


class PaiementMonetbilEchoue(RuntimeError):
    """Levée pour toute erreur d'appel à l'API Monetbil (clé absente,
    réseau, réponse malformée) -- jamais avalée silencieusement, une
    initiation de paiement qui échoue doit être visible immédiatement
    à l'élève plutôt que de le laisser croire qu'un paiement est en
    cours alors que rien n'a été envoyé."""
    pass


def _cle_service() -> str:
    cle = os.environ.get(MONETBIL_SERVICE_KEY_ENV)
    if not cle:
        raise PaiementMonetbilEchoue(
            f"{MONETBIL_SERVICE_KEY_ENV} manquant dans l'environnement -- "
            f"configure-la avant d'accepter des paiements."
        )
    return cle


def _secret_service() -> Optional[str]:
    """Retourne None (pas d'exception) si le secret n'est pas encore
    configuré -- contrairement à la clé de service, le secret n'est
    nécessaire QUE pour la signature, une couche de sécurité
    additionnelle, pas pour le fonctionnement de base de l'API."""
    return os.environ.get(MONETBIL_SERVICE_SECRET_ENV)


def signer(secret: str, params: dict) -> str:
    """Reproduit EXACTEMENT Monetbil::sign() du SDK PHP officiel :
    ksort() sur les clés, puis md5(secret + concaténation des valeurs
    dans cet ordre). Ne pas modifier cette logique sans revérifier le
    SDK officiel -- toute divergence, même minime (un espace en trop,
    un ordre différent), rend la signature invalide côté Monetbil ou
    côté nous."""
    cles_triees = sorted(params.keys())
    concatenation = "".join(str(params[cle]) for cle in cles_triees)
    return hashlib.md5((secret + concatenation).encode("utf-8")).hexdigest()


def verifier_signature_notification(params: dict) -> bool:
    """Vérifie la signature d'une notification entrante -- reproduit
    Monetbil::checkSign(). Retourne False si le secret n'est pas
    configuré OU si la signature est absente/invalide : dans les deux
    cas, l'appelant (voir app.py) doit se rabattre sur une
    vérification indépendante via verifier_paiement_par_transaction()
    plutôt que de faire confiance au contenu brut de la requête.

    Comparaison en temps constant (hmac.compare_digest) plutôt qu'un
    simple `==` -- même principe que verifier_identifiants() dans
    database_eleves.py contre les attaques par mesure de timing."""
    secret = _secret_service()
    if not secret:
        return False
    if "sign" not in params:
        return False

    params_sans_signature = {k: v for k, v in params.items() if k != "sign"}
    signature_attendue = signer(secret, params_sans_signature)
    return hmac.compare_digest(str(params["sign"]), signature_attendue)


def initier_paiement(payment_ref: str, montant: int, notify_url: str, return_url: str,
                      user: Optional[str] = None, first_name: Optional[str] = None,
                      last_name: Optional[str] = None, phone: Optional[str] = None,
                      item_ref: str = "abonnement_examenscam",
                      locale: str = "fr", country: str = "CM", currency: str = "XAF") -> str:
    """Initie un paiement -- retourne l'URL vers laquelle rediriger
    l'élève pour qu'il complète le paiement sur l'interface Monetbil.

    `payment_ref` DOIT être unique par tentative de paiement (voir
    database_paiements.creer_paiement) -- Monetbil interrompt la
    transaction si une référence déjà utilisée est réenvoyée (voir
    doc officielle : "If the order already exists, the transaction
    will be interrupted").

    Lève PaiementMonetbilEchoue si la clé de service est absente, si
    la requête réseau échoue, ou si Monetbil répond success=false --
    ne retourne JAMAIS une URL invalide ou vide silencieusement."""
    cle_service = _cle_service()
    secret = _secret_service()

    params = {
        "amount": montant,
        "phone": phone or "",
        "country": country,
        "currency": currency,
        "locale": locale,
        "item_ref": item_ref,
        "payment_ref": payment_ref,
        "user": user or "",
        "first_name": first_name or "",
        "last_name": last_name or "",
        "return_url": return_url,
        "notify_url": notify_url,
    }

    # La signature sur les paiements SORTANTS n'est utile que si
    # Monetbil la revérifie de son côté à la réception -- pas garanti
    # sur tous les comptes/versions d'API. On l'ajoute quand même si
    # le secret est disponible : ça ne peut jamais nuire, et ça
    # prépare le terrain si Monetbil l'exige un jour pour ce compte.
    if secret:
        params["sign"] = signer(secret, params)

    url = WIDGET_URL.format(service_key=cle_service)
    try:
        reponse = requests.post(url, data=params, timeout=TIMEOUT_SEC)
        reponse.raise_for_status()
        resultat = reponse.json()
    except requests.RequestException as e:
        raise PaiementMonetbilEchoue(f"Erreur réseau vers Monetbil : {e}") from e
    except ValueError as e:
        raise PaiementMonetbilEchoue(f"Réponse Monetbil illisible (pas du JSON) : {e}") from e

    if not resultat.get("success"):
        raise PaiementMonetbilEchoue(f"Monetbil a refusé l'initiation du paiement : {resultat}")

    payment_url = resultat.get("payment_url")
    if not payment_url:
        raise PaiementMonetbilEchoue(f"Réponse Monetbil sans payment_url : {resultat}")

    return payment_url


def verifier_paiement_par_transaction(transaction_id: str) -> tuple[int, bool]:
    """Deuxième couche de vérification, INDÉPENDANTE de la notification
    reçue -- interroge directement l'API Monetbil pour confirmer le
    statut réel d'une transaction plutôt que de faire confiance
    uniquement à ce qu'un POST prétend nous dire, même signature
    valide (défense en profondeur, pas une redondance inutile).

    Retourne (statut, mode_test) -- voir STATUT_* en tête de fichier
    pour la convention de valeurs.

    Lève PaiementMonetbilEchoue en cas d'erreur réseau ou de réponse
    inexploitable."""
    try:
        reponse = requests.post(CHECK_PAYMENT_URL, data={"paymentId": transaction_id}, timeout=TIMEOUT_SEC)
        reponse.raise_for_status()
        resultat = reponse.json()
    except requests.RequestException as e:
        raise PaiementMonetbilEchoue(f"Erreur réseau vers Monetbil (checkPayment) : {e}") from e
    except ValueError as e:
        raise PaiementMonetbilEchoue(f"Réponse Monetbil illisible (checkPayment) : {e}") from e

    transaction = resultat.get("transaction")
    if not transaction:
        raise PaiementMonetbilEchoue(f"Réponse checkPayment sans transaction : {resultat}")

    return int(transaction.get("status", 0)), bool(transaction.get("testmode"))