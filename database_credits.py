# database_credits.py — ExamensCam
"""
Système de crédits prépayés -- remplace le modèle d'abonnement
mensuel/hebdomadaire initialement prévu dans database_paiements.py
(voir décision du 05/09/2026 : Monetbil ne répond plus depuis
plusieurs relances, Flutterwave a répondu mais négativement -- une
dépendance à un seul prestataire d'abonnement récurrent est un risque
que le business ne peut pas se permettre de porter. Le modèle au
crédit est indépendant du prestataire de paiement : n'importe lequel
peut créditer un compte, l'abonnement récurrent n'est plus nécessaire).

═══════════════════════════════════════════════════════
RÈGLE DE FACTURATION (décidée le 05/09/2026, chiffrée sur des tarifs
réels, pas une intuition -- voir le calcul complet dans la
conversation) :
═══════════════════════════════════════════════════════

  1 crédit = 1000 tokens (entrée + sortie confondus)
  Prix de vente : 1 crédit = 1 FCFA

  Calcul de la marge (pour référence, à revérifier si les tarifs
  Gemini ou le taux de change bougent significativement) :
    - Coût réel Gemini Flash-Lite (tarif payant officiel Google,
      vérifié le 05/09/2026) : $0.10 / 1M tokens entrée,
      $0.40 / 1M tokens sortie.
    - Taux de change au 05/09/2026 : ~575 FCFA / USD.
    - Coût réel d'un "crédit" de 1000 tokens (mix 40% entrée / 60%
      sortie, représentatif d'un échange tuteur typique) :
      (400 * 0.10 + 600 * 0.40) / 1_000_000 = $0.00028 ≈ 0,16 FCFA.
    - Vendu à 1 FCFA/crédit -> marge réelle ≈ x6, au-dessus de la
      cible x4 demandée (absorbe les frais de transaction mobile
      money et l'incertitude sur le modèle Gemini exact derrière
      l'alias "gemini-flash-lite-latest", qui peut changer de version
      sans prévenir -- voir scripts/chat_llm_client.py).

  MÊME NOMBRE DE CRÉDITS QUEL QUE SOIT LE FOURNISSEUR AYANT RÉPONDU
  (décision du 05/09/2026) : que la réponse vienne de Gemini (payant)
  ou de Hugging Face (gratuit, fallback), l'élève paie le même
  nombre de crédits pour une question de longueur équivalente --
  simple et prévisible pour l'élève, qui n'a de toute façon aucun
  moyen de savoir quel fournisseur a répondu.

═══════════════════════════════════════════════════════
CRÉDITS GRATUITS MENSUELS (05/09/2026) :
═══════════════════════════════════════════════════════
  300 crédits offerts chaque mois calendaire, remis à zéro
  automatiquement (même mécanique que messages_ce_mois dans
  database_eleves.py : comparaison de 'AAAA-MM', pas de tâche planifiée
  nécessaire). Coût réel pour ExamensCam si un élève consomme tout son
  quota gratuit : 300 * 0,16 FCFA ≈ 48 FCFA/mois/élève -- largement
  soutenable pour la rétention, tout en laissant les gros
  consommateurs payer au-delà via de vrais crédits achetés.

  CE CHIFFRE (300) EST UNE PROPOSITION PAR DÉFAUT, PAS UNE DÉCISION
  DÉFINITIVE -- ajustable via CREDITS_GRATUITS_MENSUELS ci-dessous,
  un seul endroit à changer.

  Quand un élève tombe à 0 crédit (gratuit + payant épuisés) au cours
  du mois : le chat est bloqué (voir peut_poser_question()) jusqu'à
  l'achat de crédits OU le renouvellement du mois suivant -- jamais
  bloqué DÉFINITIVEMENT, un crédit gratuit revient toujours au mois
  suivant (c'est la garantie demandée le 05/09/2026), mais rien
  n'empêche un blocage temporaire en cours de mois si tout est
  consommé avant la fin.

═══════════════════════════════════════════════════════
SCHÉMA : deux tables séparées de `eleves`, plutôt que d'ajouter des
colonnes à cette table déjà stable -- limite le risque de régression
sur database_eleves.py, qui n'a pas besoin d'être touché du tout pour
ce chantier.
═══════════════════════════════════════════════════════
"""

import math
import os
from datetime import datetime
from typing import Optional

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "sur Render avec la chaine de connexion Postgres fournie par Neon "
        "-- sans elle, le systeme de credits ne peut pas fonctionner."
    )

TOKENS_PAR_CREDIT = 1000
PRIX_CREDIT_FCFA = 1
CREDITS_GRATUITS_MENSUELS = 300

TYPES_TRANSACTION = ('achat', 'consommation', 'reset_mensuel')


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def create_table():
    """Idempotent -- appelée au démarrage de app.py, jamais destructive
    sur une table existante. REFERENCES eleves(id) : si un compte
    élève est un jour supprimé, les lignes correspondantes ici doivent
    l'être explicitement AVANT (voir la suppression de compte prévue
    séparément) -- pas de ON DELETE CASCADE ici volontairement, pour
    ne jamais perdre silencieusement un historique de transactions
    financières sans décision explicite."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS credits_eleves (
                eleve_id INTEGER PRIMARY KEY REFERENCES eleves(id),
                credits_payants INTEGER NOT NULL DEFAULT 0,
                credits_gratuits_restants INTEGER NOT NULL DEFAULT 0,
                mois_credits_gratuits TEXT,
                maj_le TEXT DEFAULT (NOW()::text)
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions_credits (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                eleve_id INTEGER NOT NULL REFERENCES eleves(id),
                type TEXT NOT NULL,
                credits INTEGER NOT NULL,
                tokens_entree INTEGER,
                tokens_sortie INTEGER,
                fournisseur TEXT,
                source_modele TEXT,
                payment_ref TEXT,
                cree_le TEXT DEFAULT (NOW()::text)
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_credits_eleve ON transactions_credits(eleve_id);")
        conn.commit()
    finally:
        conn.close()


def _assurer_ligne_et_reset_mensuel(cur, eleve_id: int):
    """Crée la ligne credits_eleves si elle n'existe pas encore
    (prembelle utilisation), et remet credits_gratuits_restants à
    CREDITS_GRATUITS_MENSUELS si on a changé de mois calendaire depuis
    la dernière fois -- même mécanique que incrementer_usage_mensuel()
    dans database_eleves.py (comparaison de chaîne 'AAAA-MM',
    volontairement simple).

    Appelée à l'intérieur d'une transaction déjà ouverte (cur fourni
    par l'appelant) -- ne fait PAS son propre commit, pour que la
    création/reset et l'opération qui suit (consommation ou achat)
    restent atomiques ensemble."""
    mois_actuel = datetime.now().strftime('%Y-%m')

    cur.execute("SELECT mois_credits_gratuits FROM credits_eleves WHERE eleve_id = %s", (eleve_id,))
    ligne = cur.fetchone()

    if ligne is None:
        cur.execute("""
            INSERT INTO credits_eleves (eleve_id, credits_payants, credits_gratuits_restants, mois_credits_gratuits)
            VALUES (%s, 0, %s, %s)
        """, (eleve_id, CREDITS_GRATUITS_MENSUELS, mois_actuel))
        return

    if ligne['mois_credits_gratuits'] != mois_actuel:
        cur.execute("""
            UPDATE credits_eleves
            SET credits_gratuits_restants = %s, mois_credits_gratuits = %s, maj_le = NOW()::text
            WHERE eleve_id = %s
        """, (CREDITS_GRATUITS_MENSUELS, mois_actuel, eleve_id))
        cur.execute("""
            INSERT INTO transactions_credits (eleve_id, type, credits)
            VALUES (%s, 'reset_mensuel', %s)
        """, (eleve_id, CREDITS_GRATUITS_MENSUELS))


def calculer_credits(tokens_entree: int, tokens_sortie: int) -> int:
    """Arrondi TOUJOURS vers le haut (une fraction de crédit consommée
    est facturée comme un crédit plein) et minimum 1 -- même une
    réponse très courte a un coût réel non nul et un minimum de temps
    serveur associé."""
    total = max(0, tokens_entree) + max(0, tokens_sortie)
    return max(1, math.ceil(total / TOKENS_PAR_CREDIT))


def get_solde(eleve_id: int) -> dict:
    """Retourne {'credits_gratuits_restants', 'credits_payants', 'total'}.
    Applique le reset mensuel au passage si nécessaire -- un élève qui
    consulte son solde en tout début de mois doit voir le nouveau
    quota, pas l'ancien."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        _assurer_ligne_et_reset_mensuel(cur, eleve_id)
        conn.commit()

        cur.execute(
            "SELECT credits_payants, credits_gratuits_restants FROM credits_eleves WHERE eleve_id = %s",
            (eleve_id,)
        )
        ligne = cur.fetchone()
        return {
            'credits_gratuits_restants': ligne['credits_gratuits_restants'],
            'credits_payants': ligne['credits_payants'],
            'total': ligne['credits_gratuits_restants'] + ligne['credits_payants'],
        }
    except Exception as e:
        conn.rollback()
        print(f"get_solde error: {e}")
        return {'credits_gratuits_restants': 0, 'credits_payants': 0, 'total': 0}
    finally:
        conn.close()


def peut_poser_question(eleve_id: int) -> bool:
    """À appeler AVANT d'interroger l'IA (voir app.py,
    assistant_eleve_repondre) -- inutile de dépenser un appel Gemini
    pour ensuite découvrir que l'élève n'a plus de crédit."""
    return get_solde(eleve_id)['total'] > 0


def consommer_credits(eleve_id: int, tokens_entree: int, tokens_sortie: int,
                       fournisseur: Optional[str] = None, source_modele: Optional[str] = None) -> dict:
    """À appeler APRÈS qu'une réponse a été générée avec succès (voir
    app.py, flux_evenements -- au même endroit que
    incrementer_usage_mensuel() actuellement). Déduit d'abord les
    crédits gratuits du mois, puis les crédits payants -- ordre
    délibéré : consommer le "cadeau" avant le crédit que l'élève a
    payé de sa poche.

    Ne bloque PAS si le solde devient négatif ici -- le blocage se
    fait EN AMONT via peut_poser_question(), jamais après coup (on ne
    va pas réclamer une question déjà répondue). Si cette fonction est
    appelée sur un compte déjà à 0, le solde passe simplement en
    négatif exceptionnellement ; peut_poser_question() empêchera la
    question suivante.

    Retourne {'credits_consommes', 'solde_restant'}."""
    credits_consommes = calculer_credits(tokens_entree, tokens_sortie)

    conn = get_connection()
    try:
        cur = conn.cursor()
        _assurer_ligne_et_reset_mensuel(cur, eleve_id)

        cur.execute(
            "SELECT credits_gratuits_restants, credits_payants FROM credits_eleves WHERE eleve_id = %s",
            (eleve_id,)
        )
        ligne = cur.fetchone()

        pris_sur_gratuits = min(ligne['credits_gratuits_restants'], credits_consommes)
        reste_a_prendre = credits_consommes - pris_sur_gratuits

        nouveaux_gratuits = ligne['credits_gratuits_restants'] - pris_sur_gratuits
        nouveaux_payants = ligne['credits_payants'] - reste_a_prendre  # peut devenir negatif, voir docstring

        cur.execute("""
            UPDATE credits_eleves
            SET credits_gratuits_restants = %s, credits_payants = %s, maj_le = NOW()::text
            WHERE eleve_id = %s
        """, (nouveaux_gratuits, nouveaux_payants, eleve_id))

        cur.execute("""
            INSERT INTO transactions_credits
                (eleve_id, type, credits, tokens_entree, tokens_sortie, fournisseur, source_modele)
            VALUES (%s, 'consommation', %s, %s, %s, %s, %s)
        """, (eleve_id, -credits_consommes, tokens_entree, tokens_sortie, fournisseur, source_modele))

        conn.commit()
        return {
            'credits_consommes': credits_consommes,
            'solde_restant': nouveaux_gratuits + nouveaux_payants,
        }
    except Exception as e:
        conn.rollback()
        print(f"consommer_credits error: {e}")
        return {'credits_consommes': 0, 'solde_restant': None}
    finally:
        conn.close()


def ajouter_credits_achetes(eleve_id: int, montant_credits: int, payment_ref: Optional[str] = None) -> dict:
    """À appeler une fois un paiement CONFIRMÉ (jamais avant -- voir le
    même principe que confirmer_paiement() dans database_paiements.py
    pour l'ancien flux d'abonnement). `payment_ref` trace quelle
    transaction de paiement a généré cet ajout, pour l'audit.

    Retourne {'ok', 'solde_apres'}."""
    if montant_credits <= 0:
        return {'ok': False, 'solde_apres': None, 'erreur': "Montant de crédits invalide."}

    conn = get_connection()
    try:
        cur = conn.cursor()
        _assurer_ligne_et_reset_mensuel(cur, eleve_id)

        cur.execute(
            "UPDATE credits_eleves SET credits_payants = credits_payants + %s, maj_le = NOW()::text WHERE eleve_id = %s",
            (montant_credits, eleve_id)
        )
        cur.execute("""
            INSERT INTO transactions_credits (eleve_id, type, credits, payment_ref)
            VALUES (%s, 'achat', %s, %s)
        """, (eleve_id, montant_credits, payment_ref))

        conn.commit()
        solde = get_solde(eleve_id)
        return {'ok': True, 'solde_apres': solde['total']}
    except Exception as e:
        conn.rollback()
        print(f"ajouter_credits_achetes error: {e}")
        return {'ok': False, 'solde_apres': None, 'erreur': str(e)}
    finally:
        conn.close()


def prix_fcfa_pour_credits(nombre_credits: int) -> int:
    """Prix de vente en FCFA pour un nombre de crédits donné -- un seul
    endroit à changer si PRIX_CREDIT_FCFA évolue."""
    return nombre_credits * PRIX_CREDIT_FCFA