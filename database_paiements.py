# database_paiements.py — ExamensCam
"""
Suivi des tentatives de paiement d'abonnement -- table séparée de
`eleves` (voir database_eleves.py) pour ne jamais mélanger l'identité
de l'élève avec l'historique de ses transactions, et pour garder trace
même d'un paiement qui échoue ou n'est jamais confirmé.

`payment_ref` est un jeton aléatoire (uuid4 hex, même convention que
MOTIF_JETON_VALIDE dans app.py pour l'extraction d'en-tête) -- PAS
l'id de l'élève directement.

Ce module ne fait AUCUN appel réseau -- voir paiement_monetbil.py pour
l'intégration API.

═══════════════════════════════════════════════════════
MIGRATION POSTGRES (NEON) — 04/09/2026
═══════════════════════════════════════════════════════
Même migration que les autres modules database_*.py :
  - sqlite3.connect(DB_PATH)        -> psycopg2.connect(DATABASE_URL)
  - conn.row_factory = sqlite3.Row  -> cursor_factory=RealDictCursor
  - placeholders '?'                -> placeholders '%s'
  - datetime('now')                 -> NOW()
  - conn.execute(...) direct        -> conn.cursor() puis cur.execute(...)
  - NOUVEAU : conn.rollback() dans confirmer_paiement() -- CETTE
    FONCTION EST LA PLUS SENSIBLE DU LOT à cette différence Postgres :
    elle fait DEUX écritures liées (paiements, puis eleves) dans une
    seule transaction. Si la deuxième UPDATE échouait sans rollback
    explicite, la connexion resterait dans un état "transaction
    avortée" -- le conn.commit() final échouerait silencieusement
    d'une façon différente de SQLite, et pire, on risquerait un état
    incohérent (paiement marqué reussi sans abonnement activé, ou
    inversement) selon où exactement l'erreur survient. Le rollback
    explicite dans le except garantit qu'un échec annule TOUJOURS les
    deux écritures ensemble, jamais une seule des deux.

CE QUI NE CHANGE PAS : noms de fonctions, signatures, valeurs de
retour, logique d'idempotence de confirmer_paiement() -- aucune
modification nécessaire côté app.py.
"""

import os
import uuid
from typing import Optional
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "sur Render avec la chaine de connexion Postgres fournie par Neon "
        "-- sans elle, aucun paiement ne peut etre enregistre ni confirme."
    )

# Constantes d'abonnement -- À AJUSTER une fois le prix et la durée
# définitivement tranchés. Valeurs actuelles = valeurs de TEST, pas
# des prix définitifs -- ne pas les laisser telles quelles au
# lancement public.
MONTANT_ABONNEMENT_FCFA = 500
DUREE_ABONNEMENT_JOURS = 30

STATUTS_VALIDES = ('en_attente', 'reussi', 'echoue', 'annule')


def get_connection():
    """Retourne une connexion Postgres dont les curseurs renvoient des
    lignes de type dict (RealDictRow)."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def create_table():
    """Idempotent, comme les autres create_table() du projet -- jamais
    destructive sur une table existante. Doit être appelée APRÈS
    create_table_eleves() (dépendance de clé étrangère eleve_id ->
    eleves.id), déjà le cas dans l'ordre d'appel de app.py."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS paiements (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                payment_ref TEXT NOT NULL UNIQUE,
                eleve_id INTEGER NOT NULL,
                montant INTEGER NOT NULL,
                statut TEXT NOT NULL DEFAULT 'en_attente',
                transaction_id TEXT,
                operateur TEXT,
                date_creation TEXT DEFAULT (NOW()::text),
                date_confirmation TEXT,
                FOREIGN KEY (eleve_id) REFERENCES eleves(id)
            );
        """)
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_paiements_ref ON paiements(payment_ref);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_paiements_eleve ON paiements(eleve_id);")
        conn.commit()
    finally:
        conn.close()


def creer_paiement(eleve_id: int, montant: int = MONTANT_ABONNEMENT_FCFA) -> str:
    """Crée une nouvelle tentative de paiement en statut 'en_attente'
    et retourne le payment_ref généré -- à passer tel quel à
    paiement_monetbil.initier_paiement().

    uuid4().hex (32 caractères hexadécimaux) plutôt qu'un UUID complet
    avec tirets -- plus court à transporter dans une requête, toujours
    suffisamment imprévisible pour cet usage."""
    payment_ref = uuid.uuid4().hex
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO paiements (payment_ref, eleve_id, montant, statut)
            VALUES (%s, %s, %s, 'en_attente')
        """, (payment_ref, eleve_id, montant))
        conn.commit()
        return payment_ref
    finally:
        conn.close()


def get_paiement_par_ref(payment_ref: str) -> Optional[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM paiements WHERE payment_ref = %s", (payment_ref,)
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def confirmer_paiement(payment_ref: str, transaction_id: Optional[str],
                        statut: str, operateur: Optional[str] = None) -> Optional[str]:
    """Enregistre le résultat final d'un paiement et, SI ET SEULEMENT
    SI statut == 'reussi', active l'abonnement de l'élève concerné
    (table eleves) pour DUREE_ABONNEMENT_JOURS à partir de maintenant.

    Idempotent par construction : si ce paiement est déjà en statut
    'reussi' (notification reçue deux fois -- cas fréquent avec les
    webhooks, Monetbil peut réessayer), on ne réactive pas une
    deuxième fois la période d'abonnement à partir d'aujourd'hui.

    Retourne un message d'erreur (str) si `payment_ref` est inconnu ou
    si `statut` est invalide, None si tout s'est bien passé -- dans
    tous les cas, l'appelant (voir app.py) doit répondre 200 à
    Monetbil même en cas d'erreur ici, pour ne jamais déclencher un
    réessai en boucle sur une notification qu'on ne pourra jamais
    traiter correctement.

    MIGRATION : conn.rollback() ajouté dans le except -- cette
    fonction fait DEUX écritures liées (paiements puis eleves) dans
    une seule transaction ; voir l'avertissement en tête de fichier
    sur l'importance de ce rollback pour ne jamais laisser les deux
    tables dans un état incohérent l'une par rapport à l'autre."""
    if statut not in STATUTS_VALIDES:
        return f"Statut de paiement invalide : {statut!r}."

    paiement = get_paiement_par_ref(payment_ref)
    if not paiement:
        return f"payment_ref inconnu : {payment_ref!r}."

    if paiement['statut'] == 'reussi':
        return None  # déjà confirmé -- notification dupliquée, no-op volontaire

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE paiements
            SET statut = %s, transaction_id = %s, operateur = %s,
                date_confirmation = NOW()::text
            WHERE payment_ref = %s
        """, (statut, transaction_id, operateur, payment_ref))

        if statut == 'reussi':
            expiration = (datetime.now() + timedelta(days=DUREE_ABONNEMENT_JOURS)).strftime('%Y-%m-%d %H:%M:%S')
            cur.execute("""
                UPDATE eleves
                SET abonnement_statut = 'payant', abonnement_expire_le = %s
                WHERE id = %s
            """, (expiration, paiement['eleve_id']))

        conn.commit()
        return None
    except Exception as e:
        conn.rollback()
        print(f"confirmer_paiement error: {e}")
        return "Une erreur est survenue lors de la confirmation du paiement."
    finally:
        conn.close()


def abonnement_est_actif(eleve: dict) -> bool:
    """Vérifie si l'abonnement d'un élève est actuellement valide --
    à appeler avant de débloquer une fonctionnalité premium.

    INCHANGÉ par la migration -- logique Python pure sur un dict déjà
    chargé, pas de SQL ici."""
    if eleve.get('abonnement_statut') != 'payant':
        return False
    expire_le = eleve.get('abonnement_expire_le')
    if not expire_le:
        return False
    try:
        return datetime.strptime(expire_le, '%Y-%m-%d %H:%M:%S') > datetime.now()
    except ValueError:
        return False