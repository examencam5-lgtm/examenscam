# database_eleves.py — ExamensCam
"""
Comptes élèves — authentification + personnalisation du site et du
chat par niveau/série.

═══════════════════════════════════════════════════════
ÉVOLUTION SCHÉMA — 05/09/2026 : prénom/nom séparés + établissement
═══════════════════════════════════════════════════════
Deux colonnes ajoutées :
  - prenom  : séparé de nom pour une personnalisation fiable
              ("Bonjour, {prenom}") -- l'ancienne méthode
              (nom.split(' ')[0]) casse sur les noms composés ou les
              élèves qui ne tapent qu'un seul mot.
  - etablissement : FACULTATIF -- utilité réelle immédiate (contenu
              localisé, classement par établissement à terme), jamais
              exigé pour ne pas ajouter de friction à l'inscription.

⚠️ PRINCIPE TENU : on n'ajoute QUE des champs à utilité concrète et
immédiate. Ville, région, date de naissance précise, réseaux sociaux
NE SONT PAS ajoutés -- aucune fonctionnalité actuelle n'en a besoin,
et ce sont des données de mineurs (voir principe de minimisation
ci-dessous, inchangé depuis la conception d'origine).

MIGRATION NON-DESTRUCTIVE : `nom` change de sens (nom de famille
seul, plus nom complet) mais AUCUNE donnée existante n'est perdue ou
altérée -- les comptes créés avant cette évolution ont `prenom` vide
et gardent `nom` tel quel (nom complet historique). Les templates et
la logique d'affichage gèrent ce cas de repli automatiquement (voir
mon_compte.html et inscription.html : `eleve.prenom or
eleve.nom.split(' ')[0]`).

═══════════════════════════════════════════════════════
MIGRATION POSTGRES (NEON) — 04/09/2026 (rappel, déjà en place)
═══════════════════════════════════════════════════════
Voir la version précédente de ce fichier pour le détail complet du
passage SQLite -> Postgres. Ce qui suit ne fait qu'étendre le schéma
déjà migré.

PRINCIPES DE CONCEPTION D'ORIGINE (inchangés) :

1. MINIMISATION DES DONNÉES -- ce sont des données de mineurs, chaque
   champ collecté est un risque juridique et une responsabilité.
   Obligatoires : identifiant, mot de passe, prénom, nom, niveau
   (+ série sauf BEPC). Email, téléphone, établissement restent
   FACULTATIFS.

2. MOT DE PASSE -- hashé avec werkzeug.security (scrypt). Inchangé.

3-5. Inchangés, voir versions précédentes.
"""

import os
import re
import time
from typing import Optional
from datetime import datetime

import psycopg2
import psycopg2.extras
from psycopg2 import errors as pg_errors

from werkzeug.security import generate_password_hash, check_password_hash

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "sur Render avec la chaine de connexion Postgres fournie par Neon."
    )

NIVEAUX_VALIDES = ('BEPC', 'Probatoire', 'BAC')
SERIES_VALIDES = ('C', 'D', 'TI', 'A4', 'A')

LONGUEUR_MIN_MOT_DE_PASSE = 8
LONGUEUR_MIN_IDENTIFIANT = 3
LONGUEUR_MAX_NOM_PRENOM = 50
LONGUEUR_MAX_ETABLISSEMENT = 120

MOTIF_IDENTIFIANT_VALIDE = re.compile(r'^[a-zA-Z0-9._-]{3,32}$')

_HASH_FACTICE_POUR_TIMING = generate_password_hash("valeur-fixe-non-secrete")


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def create_table():
    """Idempotent. Les ALTER TABLE ... ADD COLUMN IF NOT EXISTS
    permettent d'étendre une table déjà créée par une version
    antérieure de ce fichier SANS perdre les comptes existants --
    c'est la façon standard d'appliquer une migration de schéma
    additive en production, plutôt que de DROP/recréer la table."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS eleves (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                identifiant TEXT NOT NULL UNIQUE,
                mot_de_passe_hash TEXT NOT NULL,
                nom TEXT NOT NULL,
                niveau TEXT NOT NULL,
                serie TEXT,
                classe TEXT,
                email TEXT,
                telephone TEXT,
                abonnement_statut TEXT NOT NULL DEFAULT 'gratuit',
                abonnement_expire_le TEXT,
                messages_ce_mois INTEGER NOT NULL DEFAULT 0,
                mois_compteur TEXT,
                date_creation TEXT DEFAULT (NOW()::text),
                derniere_connexion TEXT,
                actif INTEGER DEFAULT 1
            );
        """)
        # Migration additive -- sans effet si les colonnes existent déjà.
        cur.execute("ALTER TABLE eleves ADD COLUMN IF NOT EXISTS prenom TEXT;")
        cur.execute("ALTER TABLE eleves ADD COLUMN IF NOT EXISTS etablissement TEXT;")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_eleves_identifiant ON eleves(identifiant);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_eleves_niveau_serie ON eleves(niveau, serie);")
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════
# VALIDATION D'ENTRÉE
# ═══════════════════════════════════════════════════════

def valider_inscription(identifiant: str, mot_de_passe: str, prenom: str, nom: str,
                         niveau: str, serie: Optional[str],
                         etablissement: Optional[str] = None) -> list[str]:
    erreurs = []

    if not identifiant or not MOTIF_IDENTIFIANT_VALIDE.match(identifiant):
        erreurs.append(
            f"Identifiant invalide : {LONGUEUR_MIN_IDENTIFIANT} à 32 caractères, "
            f"lettres/chiffres/points/tirets uniquement."
        )

    if not mot_de_passe or len(mot_de_passe) < LONGUEUR_MIN_MOT_DE_PASSE:
        erreurs.append(f"Le mot de passe doit contenir au moins {LONGUEUR_MIN_MOT_DE_PASSE} caractères.")
    elif mot_de_passe.lower() == (identifiant or '').lower():
        erreurs.append("Le mot de passe ne doit pas être identique à l'identifiant.")

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
# CRÉATION DE COMPTE
# ═══════════════════════════════════════════════════════

def creer_compte(identifiant: str, mot_de_passe: str, prenom: str, nom: str, niveau: str,
                  serie: Optional[str] = None, classe: Optional[str] = None,
                  etablissement: Optional[str] = None,
                  email: Optional[str] = None, telephone: Optional[str] = None) -> tuple[Optional[int], Optional[str]]:
    """⚠️ SIGNATURE MODIFIÉE : `prenom` est un nouveau paramètre inséré
    avant `nom` -- tout appelant (voir app.py: inscription()) doit
    être mis à jour en conséquence, sans quoi les arguments positionnels
    seraient décalés silencieusement (nom reçu comme prénom, etc.)."""
    erreurs = valider_inscription(identifiant, mot_de_passe, prenom, nom, niveau, serie, etablissement)
    if erreurs:
        return None, " ".join(erreurs)

    hash_mdp = generate_password_hash(mot_de_passe)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO eleves (identifiant, mot_de_passe_hash, prenom, nom, niveau, serie, classe, etablissement, email, telephone)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (identifiant, hash_mdp, prenom.strip(), nom.strip(), niveau, serie, classe,
              (etablissement or '').strip() or None, email or None, telephone or None))
        nouvel_id = cur.fetchone()['id']
        conn.commit()
        return nouvel_id, None
    except pg_errors.UniqueViolation:
        conn.rollback()
        return None, "Cet identifiant est déjà pris -- choisis-en un autre."
    except Exception as e:
        conn.rollback()
        print(f"creer_compte error: {e}")
        return None, "Une erreur est survenue, réessaie."
    finally:
        conn.close()


def identifiant_disponible(identifiant: str) -> bool:
    """Vérification légère pour la validation en direct côté formulaire
    (voir app.py: /api/identifiant-disponible). Ne révèle rien de plus
    qu'un booléen -- pas de détail sur pourquoi un identifiant est pris,
    par cohérence avec le principe de non-énumération déjà en place
    dans verifier_identifiants()."""
    if not identifiant or not MOTIF_IDENTIFIANT_VALIDE.match(identifiant):
        return False
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM eleves WHERE identifiant = %s", (identifiant,))
        return cur.fetchone() is None
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════
# AUTHENTIFICATION
# ═══════════════════════════════════════════════════════

def verifier_identifiants(identifiant: str, mot_de_passe: str) -> Optional[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM eleves WHERE identifiant = %s AND actif = 1", (identifiant,)
        )
        row = cur.fetchone()
        if not row:
            check_password_hash(_HASH_FACTICE_POUR_TIMING, mot_de_passe)
            return None
        if not check_password_hash(row['mot_de_passe_hash'], mot_de_passe):
            return None
        return dict(row)
    except Exception as e:
        print(f"verifier_identifiants error: {e}")
        return None
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
    nom_final = nom.strip() if nom else eleve['nom']
    niveau_final = niveau or eleve['niveau']
    serie_final = serie if serie is not None else eleve['serie']
    classe_final = classe if classe is not None else eleve['classe']
    etablissement_final = etablissement if etablissement is not None else eleve.get('etablissement')

    if niveau_final not in NIVEAUX_VALIDES:
        return f"Niveau invalide (attendu : {', '.join(NIVEAUX_VALIDES)})."
    if niveau_final != 'BEPC' and not serie_final:
        return "La série est obligatoire pour ce niveau."
    if serie_final and serie_final not in SERIES_VALIDES:
        return f"Série invalide (attendu : {', '.join(SERIES_VALIDES)})."
    if not nom_final:
        return "Le nom est obligatoire."
    if not prenom_final:
        return "Le prénom est obligatoire."

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


def changer_mot_de_passe(eleve_id: int, ancien_mot_de_passe: str, nouveau_mot_de_passe: str) -> Optional[str]:
    eleve = get_eleve_par_id(eleve_id)
    if not eleve:
        return "Compte introuvable."
    if not check_password_hash(eleve['mot_de_passe_hash'], ancien_mot_de_passe):
        return "Ancien mot de passe incorrect."
    if not nouveau_mot_de_passe or len(nouveau_mot_de_passe) < LONGUEUR_MIN_MOT_DE_PASSE:
        return f"Le nouveau mot de passe doit contenir au moins {LONGUEUR_MIN_MOT_DE_PASSE} caractères."

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE eleves SET mot_de_passe_hash = %s WHERE id = %s",
            (generate_password_hash(nouveau_mot_de_passe), eleve_id)
        )
        conn.commit()
        return None
    finally:
        conn.close()


def supprimer_compte(eleve_id: int, mot_de_passe: str) -> Optional[str]:
    eleve = get_eleve_par_id(eleve_id)
    if not eleve:
        return "Compte introuvable."
    if not check_password_hash(eleve['mot_de_passe_hash'], mot_de_passe):
        return "Mot de passe incorrect."

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE eleves SET
                actif = 0,
                prenom = NULL,
                nom = 'Compte supprimé',
                identifiant = 'supprime_' || id || '_' || floor(random() * 1000000000)::text,
                mot_de_passe_hash = %s,
                email = NULL, telephone = NULL, classe = NULL, etablissement = NULL,
                derniere_connexion = NULL
            WHERE id = %s
        """, (_HASH_FACTICE_POUR_TIMING, eleve_id))
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


_TENTATIVES_PAR_IDENTIFIANT = {}
MAX_TENTATIVES_IDENTIFIANT = 6
FENETRE_BLOCAGE_IDENTIFIANT_SEC = 15 * 60


def login_identifiant_bloque(identifiant: str) -> bool:
    maintenant = time.time()
    echecs = [t for t in _TENTATIVES_PAR_IDENTIFIANT.get(identifiant, [])
              if maintenant - t < FENETRE_BLOCAGE_IDENTIFIANT_SEC]
    _TENTATIVES_PAR_IDENTIFIANT[identifiant] = echecs
    return len(echecs) >= MAX_TENTATIVES_IDENTIFIANT


def enregistrer_echec_identifiant(identifiant: str):
    _TENTATIVES_PAR_IDENTIFIANT.setdefault(identifiant, []).append(time.time())


def reinitialiser_echecs_identifiant(identifiant: str):
    _TENTATIVES_PAR_IDENTIFIANT.pop(identifiant, None)


def minutes_avant_deblocage_identifiant(identifiant: str) -> int:
    echecs = _TENTATIVES_PAR_IDENTIFIANT.get(identifiant, [])
    if not echecs:
        return 0
    plus_ancien = min(echecs)
    reste = FENETRE_BLOCAGE_IDENTIFIANT_SEC - (time.time() - plus_ancien)
    return max(1, round(reste / 60))