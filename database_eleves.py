# database_eleves.py — ExamensCam
"""
Comptes élèves — authentification + personnalisation du site et du
chat par niveau/série.

═══════════════════════════════════════════════════════
MIGRATION POSTGRES (NEON) — 04/09/2026
═══════════════════════════════════════════════════════
Ce module tournait auparavant sur SQLite (fichier data/annales.db).
Sur Render, sans disque persistant (plan gratuit), ce fichier était
effacé à chaque redéploiement ET à chaque réveil du service après mise
en veille -- un compte créé pouvait donc "disparaître" en quelques
minutes. Ce n'était pas un bug de logique, mais un problème de support
de stockage.

Migration vers Postgres géré (Neon, plan gratuit permanent, sans carte
bancaire, sans expiration) : les données vivent maintenant sur un
serveur externe, indépendant du cycle de vie du service Render.

CE QUI CHANGE (implémentation interne uniquement) :
  - sqlite3.connect(DB_PATH)        -> psycopg2.connect(DATABASE_URL)
  - conn.row_factory = sqlite3.Row  -> cursor_factory=RealDictCursor
  - placeholders '?'                -> placeholders '%s'
  - INTEGER PRIMARY KEY AUTOINCREMENT -> GENERATED ALWAYS AS IDENTITY
  - datetime('now')                 -> NOW()
  - sqlite3.IntegrityError          -> psycopg2.errors.UniqueViolation
  - conn.execute(...) direct        -> conn.cursor() puis cur.execute(...)
    (les connexions psycopg2, contrairement à sqlite3, n'exposent pas
    de raccourci .execute() sur l'objet connexion lui-même)
  - NOUVEAU : conn.rollback() dans les blocs except -- Postgres, à la
    différence de SQLite, abandonne la transaction en cours dès qu'une
    erreur survient ; il faut explicitement revenir en arrière avant
    de pouvoir réutiliser la connexion.

CE QUI NE CHANGE PAS : tous les noms de fonctions, leurs signatures,
leurs valeurs de retour, et donc TOUT app.py -- aucune modification
nécessaire côté routes Flask.

CONFIGURATION REQUISE : variable d'environnement DATABASE_URL, à
définir dans Render (Environment > Add Environment Variable), JAMAIS
en clair dans le code. Utiliser la chaîne de connexion "pooled" fournie
par Neon (contient généralement "-pooler" dans le nom d'hôte) --
indispensable pour une appli qui ouvre une connexion par requête HTTP,
sous peine d'épuiser la limite de connexions simultanées du plan
gratuit.

PRINCIPES DE CONCEPTION D'ORIGINE (inchangés, voir échange du
28/08/2026) :

1. MINIMISATION DES DONNÉES -- ce sont des données de mineurs, chaque
   champ collecté est un risque juridique et une responsabilité.
   Seuls sont STRICTEMENT obligatoires : identifiant (choisi par
   l'élève, pas un email), mot de passe, nom, niveau. La série est
   obligatoire sauf pour BEPC. Email et téléphone restent FACULTATIFS.

2. MOT DE PASSE -- hashé avec werkzeug.security (scrypt par défaut).
   Jamais de hash maison, jamais de mot de passe en clair, même dans
   les logs. INCHANGÉ par la migration.

3. SCALABLE MAIS HONNÊTE -- inchangé, voir chat_scope.py.

4. PRÊT POUR ABONNEMENT/QUOTA -- inchangé.

5. RATE-LIMITING PAR IDENTIFIANT -- reste en mémoire du process pour
   l'instant (_TENTATIVES_PAR_IDENTIFIANT). ATTENTION : ceci redevient
   un point faible réel si Render passe un jour à plusieurs instances
   simultanées (chaque instance a sa propre mémoire) -- à migrer vers
   la base ou un cache partagé (Redis) le jour où ce sera le cas. Non
   traité dans cette migration, qui se concentre sur la persistance
   des comptes.
"""

import os
import re
import time
import unicodedata
from typing import Optional
from datetime import datetime

import psycopg2
import psycopg2.extras
from psycopg2 import errors as pg_errors

from werkzeug.security import generate_password_hash, check_password_hash

# ═══════════════════════════════════════════════════════
# CONNEXION
# ═══════════════════════════════════════════════════════

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "sur Render avec la chaine de connexion Postgres fournie par Neon "
        "(utilise de preference la variante 'pooled', avec '-pooler' dans "
        "le nom d'hote) -- sans elle, aucune donnee eleve ne peut etre lue "
        "ni ecrite."
    )

# Mêmes conventions que le reste du site (voir app.py: SERIES_VALIDES,
# CATALOGUE) -- pas dupliquées à l'identique pour éviter un import
# circulaire avec app.py, mais gardées synchronisées manuellement.
NIVEAUX_VALIDES = ('BEPC', 'Probatoire', 'BAC')
SERIES_VALIDES = ('C', 'D', 'TI', 'A4', 'A')  # 'A' incluse : BEPC etablissements/Probatoire A existent déjà côté annales_externes

LONGUEUR_MIN_MOT_DE_PASSE = 8
LONGUEUR_MIN_IDENTIFIANT = 3

# Regex volontairement permissive mais sûre : lettres/chiffres/._-,
# pas d'espace ni de caractère spécial qui compliquerait une future
# recherche admin ou casserait une URL si l'identifiant y apparaît un
# jour. Pas d'email exigé dans l'identifiant -- un élève de BEPC n'a
# souvent pas d'adresse email personnelle.
MOTIF_IDENTIFIANT_VALIDE = re.compile(r'^[a-zA-Z0-9._-]{3,32}$')

# Hash factice de format valide (scrypt), jamais utilisé pour un vrai
# compte -- sert uniquement à occuper le même temps de calcul que
# check_password_hash sur un vrai hash, quand l'identifiant recherché
# n'existe pas (voir verifier_identifiants).
_HASH_FACTICE_POUR_TIMING = generate_password_hash("valeur-fixe-non-secrete")


def get_connection():
    """Retourne une connexion Postgres dont les curseurs renvoient des
    lignes de type dict (RealDictRow) -- même ergonomie que
    sqlite3.Row d'origine : row['colonne'] fonctionne à l'identique,
    dict(row) aussi. Le code appelant doit passer par conn.cursor()
    puis cur.execute(...), contrairement à sqlite3 qui autorisait
    conn.execute(...) directement."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def create_table():
    """Idempotent comme la version SQLite d'origine -- appelée au
    démarrage de app.py, jamais destructive sur une table existante."""
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

                -- Champs abonnement/quota : présents dès maintenant pour
                -- éviter une migration future, mais NON appliqués tant
                -- qu'aucune décision de facturation n'est prise (voir
                -- note 4 en tête de fichier). 'gratuit' = jamais bloqué.
                abonnement_statut TEXT NOT NULL DEFAULT 'gratuit',
                abonnement_expire_le TEXT,
                messages_ce_mois INTEGER NOT NULL DEFAULT 0,
                mois_compteur TEXT,

                date_creation TEXT DEFAULT (NOW()::text),
                derniere_connexion TEXT,
                actif INTEGER DEFAULT 1
            );
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_eleves_identifiant ON eleves(identifiant);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_eleves_niveau_serie ON eleves(niveau, serie);
        """)
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════
# VALIDATION D'ENTRÉE -- jamais faire confiance à ce qui vient du
# formulaire, même pour un champ "sans conséquence" comme le nom.
# INCHANGÉ par la migration (pure logique Python, pas de SQL).
# ═══════════════════════════════════════════════════════

def valider_inscription(identifiant: str, mot_de_passe: str, nom: str,
                         niveau: str, serie: Optional[str]) -> list[str]:
    """Retourne la liste des erreurs (vide = OK). Ne touche PAS à la
    base -- validation de format pure, l'unicité de l'identifiant est
    vérifiée séparément par creer_compte() (sous contrainte UNIQUE en
    base, la seule source de vérité fiable contre une course entre
    deux inscriptions simultanées)."""
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

    if not nom or not nom.strip():
        erreurs.append("Le nom est obligatoire.")
    elif len(nom.strip()) > 100:
        erreurs.append("Le nom est trop long.")

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

def creer_compte(identifiant: str, mot_de_passe: str, nom: str, niveau: str,
                  serie: Optional[str] = None, classe: Optional[str] = None,
                  email: Optional[str] = None, telephone: Optional[str] = None) -> tuple[Optional[int], Optional[str]]:
    """Retourne (id_eleve, erreur). id_eleve est None si erreur.

    La contrainte UNIQUE sur `identifiant` en base est la SEULE
    protection fiable contre une double inscription simultanée avec
    le même identifiant (une vérification préalable en lecture serait
    sujette à une course). On tente l'insertion directement et on
    traduit l'erreur en message utilisateur, jamais l'inverse.

    MIGRATION : sqlite3.IntegrityError -> psycopg2.errors.UniqueViolation.
    Postgres abandonne la transaction dès l'erreur -- conn.rollback()
    est nécessaire avant toute nouvelle requête sur cette connexion
    (même si ici on ferme la connexion juste après)."""
    erreurs = valider_inscription(identifiant, mot_de_passe, nom, niveau, serie)
    if erreurs:
        return None, " ".join(erreurs)

    hash_mdp = generate_password_hash(mot_de_passe)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO eleves (identifiant, mot_de_passe_hash, nom, niveau, serie, classe, email, telephone)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (identifiant, hash_mdp, nom.strip(), niveau, serie, classe, email or None, telephone or None))
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


# ═══════════════════════════════════════════════════════
# AUTHENTIFICATION
# ═══════════════════════════════════════════════════════

def verifier_identifiants(identifiant: str, mot_de_passe: str) -> Optional[dict]:
    """Retourne le dict de l'élève si les identifiants sont corrects
    ET le compte actif, None sinon. Ne distingue JAMAIS dans le
    message final "identifiant inconnu" de "mot de passe incorrect"
    (à faire respecter côté route) -- révéler qu'un identifiant existe
    déjà facilite l'énumération de comptes."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM eleves WHERE identifiant = %s AND actif = 1", (identifiant,)
        )
        row = cur.fetchone()
        if not row:
            # Toujours appeler check_password_hash même si l'identifiant
            # n'existe pas, contre un hash factice de même format --
            # évite qu'un attaquant mesure un temps de réponse plus
            # court sur les identifiants inconnus (timing attack
            # basique). Le résultat de cet appel est ignoré, seul le
            # temps passé compte.
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


def modifier_profil(eleve_id: int, nom: Optional[str] = None, niveau: Optional[str] = None,
                     serie: Optional[str] = None, classe: Optional[str] = None) -> Optional[str]:
    """Modification du profil (nom/niveau/série/classe) -- PAS le mot
    de passe ni l'identifiant, qui ont leurs propres fonctions dédiées
    (voir changer_mot_de_passe) pour ne jamais les modifier par
    inadvertance via un formulaire de profil générique.

    Retourne un message d'erreur (str) si validation échouée, None si
    tout s'est bien passé."""
    eleve = get_eleve_par_id(eleve_id)
    if not eleve:
        return "Compte introuvable."

    nom_final = nom.strip() if nom else eleve['nom']
    niveau_final = niveau or eleve['niveau']
    serie_final = serie if serie is not None else eleve['serie']
    classe_final = classe if classe is not None else eleve['classe']

    if niveau_final not in NIVEAUX_VALIDES:
        return f"Niveau invalide (attendu : {', '.join(NIVEAUX_VALIDES)})."
    if niveau_final != 'BEPC' and not serie_final:
        return "La série est obligatoire pour ce niveau."
    if serie_final and serie_final not in SERIES_VALIDES:
        return f"Série invalide (attendu : {', '.join(SERIES_VALIDES)})."
    if not nom_final:
        return "Le nom est obligatoire."

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE eleves SET nom = %s, niveau = %s, serie = %s, classe = %s
            WHERE id = %s
        """, (nom_final, niveau_final, serie_final, classe_final, eleve_id))
        conn.commit()
        return None
    except Exception as e:
        conn.rollback()
        print(f"modifier_profil error: {e}")
        return "Une erreur est survenue, réessaie."
    finally:
        conn.close()


def changer_mot_de_passe(eleve_id: int, ancien_mot_de_passe: str, nouveau_mot_de_passe: str) -> Optional[str]:
    """Exige l'ancien mot de passe -- même principe que tout
    changement de mot de passe sensible : une session dérobée
    (navigateur laissé ouvert dans une salle informatique partagée,
    cas très concret pour ce public) ne doit pas suffire à elle seule
    à prendre le contrôle définitif d'un compte en changeant le mot
    de passe sans le connaître."""
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
    """Suppression définitive du point de vue de l'élève : exige le
    mot de passe (même principe que changer_mot_de_passe -- pas de
    suppression via une session dérobée). Anonymise plutôt que DELETE
    brut pour ne pas casser les FK vers conversations/paiements tout
    en respectant le droit à l'effacement : plus aucune donnée
    identifiante ne subsiste après appel."""
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
                nom = 'Compte supprimé',
                identifiant = 'supprime_' || id || '_' || floor(random() * 1000000000)::text,
                mot_de_passe_hash = %s,
                email = NULL, telephone = NULL, classe = NULL,
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


# ═══════════════════════════════════════════════════════
# COMPTEUR D'USAGE MENSUEL -- mesure uniquement, aucune limite
# imposée pour l'instant (voir note 4 en tête de fichier).
# ═══════════════════════════════════════════════════════

def incrementer_usage_mensuel(eleve_id: int):
    """Remet le compteur à zéro si on a changé de mois calendaire
    depuis la dernière incrémentation -- mois_compteur stocke
    'AAAA-MM' pour une comparaison triviale en texte."""
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


# ═══════════════════════════════════════════════════════
# RATE-LIMITING DE CONNEXION -- PAR IDENTIFIANT D'ABORD (voir note 5
# en tête de fichier), toujours EN MÉMOIRE comme avant la migration.
# Ceci ne dépend pas de SQLite/Postgres et n'a donc pas changé --
# limite connue et acceptée : remise à zéro si Render redémarre, et
# point faible si un jour plusieurs instances tournent en parallèle.
# ═══════════════════════════════════════════════════════

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