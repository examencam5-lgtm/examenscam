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
CRÉDITS GRATUITS MENSUELS (ajusté le 06/09/2026, 300 -> 100) :
═══════════════════════════════════════════════════════
  100 crédits offerts chaque mois calendaire, remis à zéro
  automatiquement (même mécanique que messages_ce_mois dans
  database_eleves.py : comparaison de 'AAAA-MM', pas de tâche planifiée
  nécessaire).

  RAISON DE L'AJUSTEMENT (06/09/2026) : le calcul initial de 300
  crédits/mois se basait sur l'idée de "générosité pour la rétention",
  mais l'usage réel observé (~90 crédits/élève/mois pour un usage
  normal de chat) rendait ce quota quasi jamais atteint -- aucune
  pression pour recharger, donc aucune conversion vers les crédits
  payants possible. 100 crédits laisse une vraie marge pour un usage
  de chat normal, mais un élève qui génère aussi des épreuves
  d'entraînement (coût nettement plus élevé par génération, voir
  generer_epreuve_json.py) épuise son quota avant la fin du mois --
  précisément le profil le plus engagé, donc le plus susceptible de
  passer aux crédits achetés.

  Coût réel pour ExamensCam si un élève consomme tout son quota
  gratuit : 100 * 0,16 FCFA = 16 FCFA/mois/élève -- largement
  soutenable pour la rétention, même à grande échelle.

  CE CHIFFRE (100) EST UNE PROPOSITION, PAS UNE DÉCISION DÉFINITIVE --
  ajustable via CREDITS_GRATUITS_MENSUELS ci-dessous, un seul endroit
  à changer.

  Quand un élève tombe à 0 crédit (gratuit + payant épuisés) au cours
  du mois : le chat est bloqué (voir peut_poser_question()) jusqu'à
  l'achat de crédits OU le renouvellement du mois suivant -- jamais
  bloqué DÉFINITIVEMENT, un crédit gratuit revient toujours au mois
  suivant (c'est la garantie demandée le 05/09/2026), mais rien
  n'empêche un blocage temporaire en cours de mois si tout est
  consommé avant la fin.

═══════════════════════════════════════════════════════
RECHARGE MANUELLE (06/09/2026) — voir la conversation du même jour
pour le raisonnement complet :
═══════════════════════════════════════════════════════
  Aucun prestataire de paiement automatisé n'est accessible tant que
  le RCCM de Muhammad n'est pas enregistré (CinetPay, Flutterwave,
  Monetbil, ET NotchPay -- vérifié le 06/09/2026, NotchPay exige lui
  aussi un numéro d'immatriculation et une adresse fiscale à
  l'inscription business, donc pas de raccourci disponible non plus
  de ce côté). Le flux retenu, réaliste pour un lancement sans
  personne morale :

    1. L'élève envoie lui-même le montant du pack choisi vers le
       numéro Mobile Money PERSONNEL de Muhammad (transfert normal,
       *126# MTN ou #150# Orange).
    2. Il soumet un formulaire (voir demander_recharge()) avec son
       numéro, l'opérateur, et la référence de transaction reçue par
       SMS.
    3. Muhammad compare, une fois par jour (voir
       lister_demandes_en_attente()), ces demandes à ses propres SMS
       de réception, et valide en lot (voir valider_demande_recharge())
       celles qui correspondent exactement (numéro + montant +
       référence).

  Ceci reste un contournement TEMPORAIRE : dès qu'un vrai prestataire
  devient accessible (RCCM enregistré, cible : décembre 2026), ce
  flux manuel est remplacé par une vérification automatique côté API,
  sans changer le schéma de credits_eleves / transactions_credits
  eux-mêmes (payment_ref existe déjà et sert à tracer aussi bien un
  ajout manuel qu'un futur webhook automatique).

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
CREDITS_GRATUITS_MENSUELS = 100

TYPES_TRANSACTION = ('achat', 'consommation', 'reset_mensuel')

# ═══════════════════════════════════════════════════════
# GRILLE DE PACKS DE RECHARGE (06/09/2026)
# ═══════════════════════════════════════════════════════
#
# Calée sur la culture du crédit téléphonique camerounais (recharges
# MTN/Orange à 100, 200, 500, 1000 FCFA) plutôt que sur des montants
# "logiciels" arbitraires -- principe explicite de Muhammad : un
# élève qui a déjà le réflexe de recharger son forfait à ces montants
# n'a aucune friction mentale à faire pareil ici.
#
# Prime croissante sur les gros montants (crédits/FCFA plus généreux
# au-dessus) pour encourager l'achat groupé, sans jamais descendre
# sous une marge confortable -- vérifié avec le coût réel de
# 0,16 FCFA/crédit (même base que le calcul de marge en tête de
# fichier) :
#
#   Pack     Prix FCFA  Crédits  Coût réel  Bénéfice net  Marge
#   Micro    100        100      16 FCFA    84 FCFA       x6,25
#   Petit    200        220      35 FCFA    165 FCFA      x5,68
#   Standard 500        600      96 FCFA    404 FCFA      x5,2
#   Confort  1000       1300     208 FCFA   792 FCFA      x4,8
#
# Format : liste de dicts plutôt que juste des tuples -- un id stable
# et lisible (pack['id']) est nécessaire pour que le front-end
# référence un pack sans dépendre de sa position dans la liste, qui
# peut changer si l'ordre est retouché plus tard.
PACKS_RECHARGE = [
    {'id': 'micro', 'label': 'Micro', 'prix_fcfa': 100, 'credits': 100},
    {'id': 'petit', 'label': 'Petit', 'prix_fcfa': 200, 'credits': 220},
    {'id': 'standard', 'label': 'Standard', 'prix_fcfa': 500, 'credits': 600},
    {'id': 'confort', 'label': 'Confort', 'prix_fcfa': 1000, 'credits': 1300},
]

# Opérateurs Mobile Money supportés pour la recharge manuelle -- voir
# demander_recharge() plus bas. Limité à ces deux valeurs pour éviter
# une saisie libre incohérente (ex: fautes de frappe) dans une colonne
# qui sert ensuite à la vérification manuelle par Muhammad.
OPERATEURS_MOBILE_MONEY = ('mtn', 'orange')

STATUTS_DEMANDE_RECHARGE = ('attente', 'validee', 'rejetee')


def get_pack_par_id(pack_id: str) -> Optional[dict]:
    """Cherche un pack par son id dans PACKS_RECHARGE -- None si
    l'id ne correspond à rien de connu (permet à l'appelant de
    distinguer "pack invalide" d'une KeyError qui casserait tout)."""
    for pack in PACKS_RECHARGE:
        if pack['id'] == pack_id:
            return pack
    return None


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def create_table():
    """Idempotent -- appelée au démarrage de app.py, jamais destructive
    sur une table existante. REFERENCES eleves(id) : si un compte
    élève est un jour supprimé, les lignes correspondantes ici doivent
    l'être explicitement AVANT (voir la suppression de compte prévue
    séparément) -- pas de ON DELETE CASCADE ici volontairement, pour
    ne jamais perdre silencieusement un historique de transactions
    financières sans décision explicite.

    MODIFIÉ (06/09/2026) : ajoute aussi demandes_recharge -- la table
    qui porte le flux manuel de paiement (voir la section "RECHARGE
    MANUELLE" en tête de fichier). Même principe d'idempotence,
    même absence de CASCADE."""
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

        # NOUVEAU (06/09/2026) : file d'attente des recharges manuelles.
        # `pack_id` recopié tel quel (pas de FOREIGN KEY vers
        # PACKS_RECHARGE, qui est une liste Python, pas une table --
        # si la grille change plus tard, une demande déjà en base garde
        # la trace du pack tel qu'il existait au moment de la demande).
        # `montant_declare_fcfa` et `credits_si_valide` sont dupliqués
        # depuis le pack au moment de la demande, pour la même raison :
        # ne jamais dépendre d'une grille qui peut changer entre la
        # demande et la validation.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS demandes_recharge (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                eleve_id INTEGER NOT NULL REFERENCES eleves(id),
                pack_id TEXT NOT NULL,
                montant_declare_fcfa INTEGER NOT NULL,
                credits_si_valide INTEGER NOT NULL,
                operateur TEXT NOT NULL,
                telephone_envoyeur TEXT NOT NULL,
                reference_operateur TEXT NOT NULL,
                statut TEXT NOT NULL DEFAULT 'attente',
                note_admin TEXT,
                cree_le TEXT DEFAULT (NOW()::text),
                traite_le TEXT
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_demandes_recharge_statut ON demandes_recharge(statut);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_demandes_recharge_eleve ON demandes_recharge(eleve_id);")

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

    Utilisée à la fois par ajouter_credits_manuel.py (test CLI direct)
    et par valider_demande_recharge() ci-dessous (flux de recharge
    manuelle réel) -- reste le SEUL point d'entrée qui modifie
    credits_payants, pour garantir qu'aucun chemin ne peut créditer un
    élève sans laisser de trace dans transactions_credits.

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


# ═══════════════════════════════════════════════════════
# RECHARGE MANUELLE (06/09/2026) -- voir la section dédiée en tête de
# fichier pour le raisonnement complet du flux.
# ═══════════════════════════════════════════════════════

def demander_recharge(eleve_id: int, pack_id: str, operateur: str,
                       telephone_envoyeur: str, reference_operateur: str) -> dict:
    """Appelée quand l'élève soumet le formulaire de recharge (voir
    route Flask à créer côté app.py, ex: POST /mes-credits/recharger).

    NE CRÉDITE RIEN -- se contente d'enregistrer la demande en attente
    de vérification manuelle par Muhammad (voir
    lister_demandes_en_attente() / valider_demande_recharge()).

    Valide `pack_id` et `operateur` contre les valeurs connues plutôt
    que de faire confiance à ce qu'envoie le front-end -- une requête
    forgée avec un pack_id inventé ne doit pas pouvoir créer une
    demande avec un `credits_si_valide` arbitraire.

    Retourne {'ok', 'demande_id'} ou {'ok': False, 'erreur': ...}."""
    pack = get_pack_par_id(pack_id)
    if pack is None:
        return {'ok': False, 'erreur': f"Pack inconnu : {pack_id!r}."}

    operateur = (operateur or '').strip().lower()
    if operateur not in OPERATEURS_MOBILE_MONEY:
        return {'ok': False, 'erreur': f"Opérateur invalide : {operateur!r} (attendu 'mtn' ou 'orange')."}

    telephone_envoyeur = (telephone_envoyeur or '').strip()
    reference_operateur = (reference_operateur or '').strip()
    if not telephone_envoyeur or not reference_operateur:
        return {'ok': False, 'erreur': "Numéro de téléphone et référence de transaction obligatoires."}

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO demandes_recharge
                (eleve_id, pack_id, montant_declare_fcfa, credits_si_valide,
                 operateur, telephone_envoyeur, reference_operateur, statut)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'attente')
            RETURNING id
        """, (eleve_id, pack['id'], pack['prix_fcfa'], pack['credits'],
              operateur, telephone_envoyeur, reference_operateur))
        demande_id = cur.fetchone()['id']
        conn.commit()
        return {'ok': True, 'demande_id': demande_id}
    except Exception as e:
        conn.rollback()
        print(f"demander_recharge error: {e}")
        return {'ok': False, 'erreur': str(e)}
    finally:
        conn.close()


def lister_demandes_en_attente() -> list[dict]:
    """Pour la page admin de validation groupée -- une ligne par
    demande, la plus ancienne en premier (FIFO : un élève qui a
    attendu plus longtemps est traité en priorité). Jointure sur
    eleves pour afficher le nom sans obliger Muhammad à retenir des
    eleve_id par cœur en comparant à ses SMS."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT d.id, d.eleve_id, e.nom AS eleve_nom, d.pack_id,
                   d.montant_declare_fcfa, d.credits_si_valide, d.operateur,
                   d.telephone_envoyeur, d.reference_operateur, d.cree_le
            FROM demandes_recharge d
            JOIN eleves e ON e.id = d.eleve_id
            WHERE d.statut = 'attente'
            ORDER BY d.cree_le ASC
        """)
        return cur.fetchall()
    finally:
        conn.close()


def valider_demande_recharge(demande_id: int) -> dict:
    """Appelée par Muhammad depuis la page admin, une fois qu'il a
    comparé la demande à ses propres SMS de réception et confirmé la
    correspondance (numéro + montant + référence).

    Fait DEUX choses de façon atomique : crédite l'élève via
    ajouter_credits_achetes() (payment_ref = référence opérateur
    déclarée, pour l'audit), puis marque la demande 'validee'.

    Refuse si la demande n'existe pas ou n'est plus en 'attente'
    (déjà traitée) -- évite un double crédit si Muhammad clique deux
    fois par erreur sur la même ligne."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT eleve_id, credits_si_valide, reference_operateur, statut "
            "FROM demandes_recharge WHERE id = %s",
            (demande_id,)
        )
        demande = cur.fetchone()

        if demande is None:
            return {'ok': False, 'erreur': f"Demande {demande_id} introuvable."}
        if demande['statut'] != 'attente':
            return {'ok': False, 'erreur': f"Demande {demande_id} déjà traitée (statut : {demande['statut']})."}

        resultat_credit = ajouter_credits_achetes(
            demande['eleve_id'], demande['credits_si_valide'], demande['reference_operateur']
        )
        if not resultat_credit['ok']:
            return {'ok': False, 'erreur': f"Échec de l'ajout de crédits : {resultat_credit.get('erreur')}"}

        cur.execute("""
            UPDATE demandes_recharge
            SET statut = 'validee', traite_le = NOW()::text
            WHERE id = %s
        """, (demande_id,))
        conn.commit()

        return {'ok': True, 'solde_apres': resultat_credit['solde_apres']}
    except Exception as e:
        conn.rollback()
        print(f"valider_demande_recharge error: {e}")
        return {'ok': False, 'erreur': str(e)}
    finally:
        conn.close()


def rejeter_demande_recharge(demande_id: int, note_admin: Optional[str] = None) -> dict:
    """Pour le cas où la demande ne correspond à aucun SMS reçu
    (numéro/montant/référence incohérents) -- ne crédite rien, marque
    juste la demande 'rejetee' avec une note optionnelle pour garder
    une trace de la raison (utile si l'élève réclame plus tard)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT statut FROM demandes_recharge WHERE id = %s",
            (demande_id,)
        )
        demande = cur.fetchone()
        if demande is None:
            return {'ok': False, 'erreur': f"Demande {demande_id} introuvable."}
        if demande['statut'] != 'attente':
            return {'ok': False, 'erreur': f"Demande {demande_id} déjà traitée (statut : {demande['statut']})."}

        cur.execute("""
            UPDATE demandes_recharge
            SET statut = 'rejetee', note_admin = %s, traite_le = NOW()::text
            WHERE id = %s
        """, (note_admin, demande_id))
        conn.commit()
        return {'ok': True}
    except Exception as e:
        conn.rollback()
        print(f"rejeter_demande_recharge error: {e}")
        return {'ok': False, 'erreur': str(e)}
    finally:
        conn.close()