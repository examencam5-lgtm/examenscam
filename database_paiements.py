# database_paiements.py — ExamensCam
"""
Suivi des tentatives de paiement d'abonnement -- table séparée de
`eleves` (voir database_eleves.py) pour ne jamais mélanger l'identité
de l'élève avec l'historique de ses transactions, et pour garder trace
même d'un paiement qui échoue ou n'est jamais confirmé.

`payment_ref` est un jeton aléatoire (uuid4 hex, même convention que
MOTIF_JETON_VALIDE dans app.py pour l'extraction d'en-tête) -- PAS
l'id de l'élève directement. Utiliser l'id brut serait devinable et
énumérable (un tiers pourrait tenter de forger des notifications pour
d'autres élèves) ; un jeton aléatoire à usage unique élimine ce risque
sans complexité supplémentaire.

Ce module ne fait AUCUN appel réseau -- voir paiement_monetbil.py pour
l'intégration API. Séparation volontaire, même principe que
database_eleves.py vs gemini_client.py : la logique de stockage ne
doit jamais dépendre de la disponibilité d'un service externe.
"""

import sqlite3
import uuid
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta

DB_PATH = Path('data') / 'annales.db'

# Constantes d'abonnement -- À AJUSTER une fois le prix et la durée
# définitivement tranchés (voir discussion modèle économique du
# 02/09/2026). Valeurs actuelles = valeurs de TEST, pas des prix
# définitifs -- ne pas les laisser telles quelles au lancement public.
MONTANT_ABONNEMENT_FCFA = 500
DUREE_ABONNEMENT_JOURS = 30

STATUTS_VALIDES = ('en_attente', 'reussi', 'echoue', 'annule')


def get_connection():
    Path('data').mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_table():
    """Idempotent, comme les autres create_table() du projet -- jamais
    destructive sur une table existante."""
    Path('data').mkdir(exist_ok=True)
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS paiements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_ref TEXT NOT NULL UNIQUE,
            eleve_id INTEGER NOT NULL,
            montant INTEGER NOT NULL,
            statut TEXT NOT NULL DEFAULT 'en_attente',
            transaction_id TEXT,
            operateur TEXT,
            date_creation TEXT DEFAULT (datetime('now')),
            date_confirmation TEXT,
            FOREIGN KEY (eleve_id) REFERENCES eleves(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_paiements_ref ON paiements(payment_ref);
        CREATE INDEX IF NOT EXISTS idx_paiements_eleve ON paiements(eleve_id);
    """)
    conn.commit()
    conn.close()


def creer_paiement(eleve_id: int, montant: int = MONTANT_ABONNEMENT_FCFA) -> str:
    """Crée une nouvelle tentative de paiement en statut 'en_attente'
    et retourne le payment_ref généré -- à passer tel quel à
    paiement_monetbil.initier_paiement().

    uuid4().hex (32 caractères hexadécimaux) plutôt qu'un UUID complet
    avec tirets -- plus court à transporter dans une requête, toujours
    suffisamment imprévisible pour cet usage (même format que les
    jetons d'extraction d'en-tête ailleurs sur le site)."""
    payment_ref = uuid.uuid4().hex
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO paiements (payment_ref, eleve_id, montant, statut)
            VALUES (?, ?, ?, 'en_attente')
        """, (payment_ref, eleve_id, montant))
        conn.commit()
        return payment_ref
    finally:
        conn.close()


def get_paiement_par_ref(payment_ref: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM paiements WHERE payment_ref = ?", (payment_ref,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def confirmer_paiement(payment_ref: str, transaction_id: Optional[str],
                        statut: str, operateur: Optional[str] = None) -> Optional[str]:
    """Enregistre le résultat final d'un paiement et, SI ET SEULEMENT
    SI statut == 'reussi', active l'abonnement de l'élève concerné
    (table eleves, voir database_eleves.py) pour DUREE_ABONNEMENT_JOURS
    à partir de maintenant.

    Idempotent par construction : si ce paiement est déjà en statut
    'reussi' (notification reçue deux fois -- cas fréquent avec les
    webhooks, Monetbil peut réessayer), on ne réactive pas une
    deuxième fois la période d'abonnement à partir d'aujourd'hui, ce
    qui léserait l'élève en écrasant le temps déjà couru. On se
    contente de confirmer sans rien changer.

    Retourne un message d'erreur (str) si `payment_ref` est inconnu ou
    si `statut` est invalide, None si tout s'est bien passé -- dans
    tous les cas, l'appelant (voir app.py) doit répondre 200 à
    Monetbil même en cas d'erreur ici, pour ne jamais déclencher un
    réessai en boucle sur une notification qu'on ne pourra jamais
    traiter correctement."""
    if statut not in STATUTS_VALIDES:
        return f"Statut de paiement invalide : {statut!r}."

    paiement = get_paiement_par_ref(payment_ref)
    if not paiement:
        return f"payment_ref inconnu : {payment_ref!r}."

    if paiement['statut'] == 'reussi':
        return None  # déjà confirmé -- notification dupliquée, no-op volontaire

    conn = get_connection()
    try:
        conn.execute("""
            UPDATE paiements
            SET statut = ?, transaction_id = ?, operateur = ?,
                date_confirmation = datetime('now')
            WHERE payment_ref = ?
        """, (statut, transaction_id, operateur, payment_ref))

        if statut == 'reussi':
            expiration = (datetime.now() + timedelta(days=DUREE_ABONNEMENT_JOURS)).strftime('%Y-%m-%d %H:%M:%S')
            conn.execute("""
                UPDATE eleves
                SET abonnement_statut = 'payant', abonnement_expire_le = ?
                WHERE id = ?
            """, (expiration, paiement['eleve_id']))

        conn.commit()
        return None
    except Exception as e:
        print(f"confirmer_paiement error: {e}")
        return "Une erreur est survenue lors de la confirmation du paiement."
    finally:
        conn.close()


def abonnement_est_actif(eleve: dict) -> bool:
    """Vérifie si l'abonnement d'un élève est actuellement valide --
    à appeler avant de débloquer une fonctionnalité premium (ex: chat
    illimité, génération d'épreuve). Prend le dict élève déjà chargé
    (voir database_eleves.get_eleve_par_id) plutôt que de refaire une
    requête, pour éviter une lecture base superflue à chaque message
    de chat."""
    if eleve.get('abonnement_statut') != 'payant':
        return False
    expire_le = eleve.get('abonnement_expire_le')
    if not expire_le:
        return False
    try:
        return datetime.strptime(expire_le, '%Y-%m-%d %H:%M:%S') > datetime.now()
    except ValueError:
        return False