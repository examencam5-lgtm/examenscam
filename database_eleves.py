# database_eleves.py — ExamensCam
"""
Comptes élèves — authentification exclusivement via Google Sign-In.

═══════════════════════════════════════════════════════
REFONTE (10/09/2026) — Abandon du couple identifiant/mot de passe
═══════════════════════════════════════════════════════
RAISON : un identifiant texte libre (3-32 caractères, aucune
vérification) n'impose aucun coût réel à la création d'un nouveau
compte -- un élève à 0 crédit recréait un compte en quelques secondes.
Un compte Google authentique impose une vérification (numéro de
téléphone dans la grande majorité des cas) que Google gère à notre
place, gratuitement, sans que nous ayons à opérer nous-mêmes un
service de vérification (SMS OTP payant, etc.).

CONSÉQUENCE DIRECTE SUR LA RESPONSABILITÉ : nous ne stockons plus
AUCUN mot de passe, même hashé. Toute la surface d'attaque liée au
mot de passe (force brute, réinitialisation, fuite de hash) disparaît
du produit -- ce n'est plus notre responsabilité, c'est celle de
Google.

CE QUI NE CHANGE PAS : le principe de minimisation des données reste
entier. On ne demande à Google que l'email et l'identifiant unique
(sub) -- pas les contacts, pas les photos, pas l'agenda. prenom/nom/
niveau/serie/classe/etablissement restent des champs renseignés par
l'élève lui-même après sa première connexion, exactement comme avant.

IDENTIFIANT UNIQUE : `google_sub` (le "subject" du token OpenID
Connect renvoyé par Google) -- une chaîne stable, jamais réattribuée
à quelqu'un d'autre, contrairement à l'email qui peut théoriquement
changer de titulaire dans de rares cas. C'est la clé d'unicité, pas
l'email.

MIGRATION : aucune -- décision explicite de Muhammad de repartir sur
une table vierge plutôt que de migrer les comptes de test existants
(couple identifiant/mot de passe). Les comptes de test créés avant
cette refonte sont donc perdus, ce qui est acceptable car ce sont des
comptes de test uniquement.
"""

import os
from typing import Optional
from datetime import datetime

import psycopg2
import psycopg2.extras
from psycopg2 import errors as pg_errors

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "sur Render avec la chaine de connexion Postgres fournie par Neon."
    )

NIVEAUX_VALIDES = ('BEPC', 'Probatoire', 'BAC')
SERIES_VALIDES = ('C', 'D', 'TI', 'A4', 'A')

LONGUEUR_MAX_NOM_PRENOM = 50
LONGUEUR_MAX_ETABLISSEMENT = 120


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def create_table():
    """Idempotent -- appelée au démarrage de app.py.

    Différence avec l'ancienne version : plus de mot_de_passe_hash, plus
    d'identifiant texte libre. `google_sub` est la clé d'unicité réelle ;
    `email` reste indexé pour un éventuel usage de contact (facultatif
    fonctionnellement, mais toujours présent puisque Google le fournit
    systématiquement lors du consentement OAuth).

    `profil_complet` : un élève a une ligne créée dès sa première
    connexion Google (avant même d'avoir choisi son niveau/série) --
    ce booléen distingue "compte technique existant" de "élève a
    terminé son profil", pour rediriger correctement après connexion.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS eleves (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                google_sub TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                prenom TEXT,
                nom TEXT,
                niveau TEXT,
                serie TEXT,
                classe TEXT,
                etablissement TEXT,
                profil_complet INTEGER NOT NULL DEFAULT 0,
                consentement_parental INTEGER NOT NULL DEFAULT 0,
                consentement_parental_le TEXT,
                messages_ce_mois INTEGER NOT NULL DEFAULT 0,
                mois_compteur TEXT,
                date_creation TEXT DEFAULT (NOW()::text),
                derniere_connexion TEXT,
                actif INTEGER DEFAULT 1
            );
        """)
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_eleves_google_sub ON eleves(google_sub);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_eleves_niveau_serie ON eleves(niveau, serie);")
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════
# VALIDATION DU PROFIL (post-connexion Google)
# ═══════════════════════════════════════════════════════

def valider_profil(prenom: str, nom: str, niveau: str, serie: Optional[str],
                    etablissement: Optional[str] = None) -> list[str]:
    erreurs = []

    if not prenom or not prenom.strip():
        erreurs.append("Le prénom est obligatoire.")
    elif len(prenom.strip()) > LONGUEUR_MAX_NOM_PRENOM:
        erreurs.append("Le prénom est trop long.")

    if not nom or not nom.strip():
        erreurs.append("Le nom est obligatoire.")
    elif len(nom.strip()) > LONGUEUR_MAX_NOM_PRENOM:
        erreurs.append("Le nom est trop long.")

    if etablissement and len(etablissement.strip()) > LONGUEUR_MAX_ETABLISSEMENT:
        erreurs.append("Le nom de l'établissement est trop long.")

    if niveau not in NIVEAUX_VALIDES:
        erreurs.append(f"Niveau invalide (attendu : {', '.join(NIVEAUX_VALIDES)}).")
    elif niveau != 'BEPC' and not serie:
        erreurs.append("La série est obligatoire pour ce niveau.")
    elif serie and serie not in SERIES_VALIDES:
        erreurs.append(f"Série invalide (attendu : {', '.join(SERIES_VALIDES)}).")

    return erreurs


# ═══════════════════════════════════════════════════════
# AUTHENTIFICATION GOOGLE
# ═══════════════════════════════════════════════════════

def creer_ou_recuperer_compte_google(google_sub: str, email: str) -> dict:
    """Point d'entrée unique après vérification réussie du token Google
    côté route Flask (voir app.py: /connexion/google/callback).

    Ne prend QUE google_sub et email -- rien d'autre n'est extrait du
    token Google, conformément au principe de minimisation. Si un
    compte existe déjà pour ce google_sub, on le retourne tel quel
    (pas de mise à jour de l'email à chaque connexion : si l'élève
    change d'email Google, google_sub reste la clé stable).

    Retourne toujours un dict complet de la ligne eleves -- jamais
    None, puisque cette fonction crée le compte s'il n'existe pas.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM eleves WHERE google_sub = %s AND actif = 1", (google_sub,))
        ligne = cur.fetchone()
        if ligne:
            return dict(ligne)

        cur.execute("""
            INSERT INTO eleves (google_sub, email)
            VALUES (%s, %s)
            RETURNING *
        """, (google_sub, email))
        nouvelle_ligne = cur.fetchone()
        conn.commit()
        return dict(nouvelle_ligne)
    except pg_errors.UniqueViolation:
        # Course possible si deux requêtes arrivent en même temps pour
        # le même nouvel utilisateur (double-clic sur "Se connecter") --
        # on relit simplement la ligne créée par l'autre requête.
        conn.rollback()
        cur = conn.cursor()
        cur.execute("SELECT * FROM eleves WHERE google_sub = %s", (google_sub,))
        return dict(cur.fetchone())
    finally:
        conn.close()


def completer_profil(eleve_id: int, prenom: str, nom: str, niveau: str,
                      serie: Optional[str], classe: Optional[str] = None,
                      etablissement: Optional[str] = None,
                      consentement_parental: bool = False) -> Optional[str]:
    """Appelée juste après la première connexion Google, quand l'élève
    renseigne son profil scolaire (niveau/série/établissement).

    `consentement_parental` : case à cocher explicite côté formulaire
    pour les élèves mineurs -- voir la politique de confidentialité.
    Ce n'est pas une vérification d'identité du parent (techniquement
    impossible à coût nul), mais un geste de consentement déclaratif
    tracé avec horodatage, préférable à une absence totale de mention.
    """
    erreurs = valider_profil(prenom, nom, niveau, serie, etablissement)
    if erreurs:
        return " ".join(erreurs)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE eleves SET
                prenom = %s, nom = %s, niveau = %s, serie = %s,
                classe = %s, etablissement = %s,
                profil_complet = 1,
                consentement_parental = %s,
                consentement_parental_le = CASE WHEN %s THEN NOW()::text ELSE consentement_parental_le END
            WHERE id = %s
        """, (prenom.strip(), nom.strip(), niveau, serie, classe,
              (etablissement or '').strip() or None,
              1 if consentement_parental else 0,
              consentement_parental, eleve_id))
        conn.commit()
        return None
    except Exception as e:
        conn.rollback()
        print(f"completer_profil error: {e}")
        return "Une erreur est survenue, réessaie."
    finally:
        conn.close()


def marquer_connexion(eleve_id: int):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE eleves SET derniere_connexion = NOW()::text WHERE id = %s", (eleve_id,))
        conn.commit()
    finally:
        conn.close()


def get_eleve_par_id(eleve_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM eleves WHERE id = %s AND actif = 1", (eleve_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def modifier_profil(eleve_id: int, prenom: Optional[str] = None, nom: Optional[str] = None,
                     niveau: Optional[str] = None, serie: Optional[str] = None,
                     classe: Optional[str] = None, etablissement: Optional[str] = None) -> Optional[str]:
    eleve = get_eleve_par_id(eleve_id)
    if not eleve:
        return "Compte introuvable."

    prenom_final = prenom.strip() if prenom else eleve.get('prenom')
    nom_final = nom.strip() if nom else eleve.get('nom')
    niveau_final = niveau or eleve['niveau']
    serie_final = serie if serie is not None else eleve['serie']
    classe_final = classe if classe is not None else eleve['classe']
    etablissement_final = etablissement if etablissement is not None else eleve.get('etablissement')

    erreurs = valider_profil(prenom_final, nom_final, niveau_final, serie_final, etablissement_final)
    if erreurs:
        return " ".join(erreurs)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE eleves SET prenom = %s, nom = %s, niveau = %s, serie = %s, classe = %s, etablissement = %s
            WHERE id = %s
        """, (prenom_final, nom_final, niveau_final, serie_final, classe_final,
              (etablissement_final or '').strip() or None, eleve_id))
        conn.commit()
        return None
    except Exception as e:
        conn.rollback()
        print(f"modifier_profil error: {e}")
        return "Une erreur est survenue, réessaie."
    finally:
        conn.close()


def supprimer_compte(eleve_id: int) -> Optional[str]:
    """Plus de vérification par mot de passe -- la suppression se fait
    depuis une session déjà authentifiée par Google (le token de
    session Flask suffit, exactement comme pour modifier_profil).
    L'anonymisation reste identique à l'ancienne version : on ne perd
    pas l'historique de transactions_credits/conversations lié à
    eleve_id, on coupe juste le lien vers une identité reconnaissable.
    """
    eleve = get_eleve_par_id(eleve_id)
    if not eleve:
        return "Compte introuvable."

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE eleves SET
                actif = 0,
                prenom = NULL,
                nom = 'Compte supprimé',
                email = 'supprime_' || id || '@examenscam.invalid',
                google_sub = 'supprime_' || id || '_' || floor(random() * 1000000000)::text,
                classe = NULL, etablissement = NULL,
                derniere_connexion = NULL
            WHERE id = %s
        """, (eleve_id,))
        conn.commit()
        return None
    except Exception as e:
        conn.rollback()
        print(f"supprimer_compte error: {e}")
        return "Une erreur est survenue, réessaie."
    finally:
        conn.close()


def incrementer_usage_mensuel(eleve_id: int):
    mois_actuel = datetime.now().strftime('%Y-%m')
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT mois_compteur FROM eleves WHERE id = %s", (eleve_id,))
        row = cur.fetchone()
        if not row:
            return
        if row['mois_compteur'] != mois_actuel:
            cur.execute(
                "UPDATE eleves SET messages_ce_mois = 1, mois_compteur = %s WHERE id = %s",
                (mois_actuel, eleve_id)
            )
        else:
            cur.execute(
                "UPDATE eleves SET messages_ce_mois = messages_ce_mois + 1 WHERE id = %s",
                (eleve_id,)
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"incrementer_usage_mensuel error: {e}")
    finally:
        conn.close()