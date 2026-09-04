# database_conversations.py — ExamensCam
"""
Persistance des conversations du chat élève.

═══════════════════════════════════════════════════════
MIGRATION POSTGRES (NEON) — 04/09/2026
═══════════════════════════════════════════════════════
Même migration que database_eleves.py (voir l'en-tête de ce fichier
pour le raisonnement complet) : SQLite sur disque éphémère Render ->
Postgres géré chez Neon, via la variable d'environnement DATABASE_URL.

CE QUI CHANGE (implémentation interne uniquement) :
  - sqlite3.connect(DB_PATH)        -> psycopg2.connect(DATABASE_URL)
  - conn.row_factory = sqlite3.Row  -> cursor_factory=RealDictCursor
  - placeholders '?'                -> placeholders '%s'
  - INTEGER PRIMARY KEY AUTOINCREMENT -> GENERATED ALWAYS AS IDENTITY
  - datetime('now')                 -> NOW()
  - cur.lastrowid                   -> clause RETURNING id + fetchone()
  - conn.execute(...) direct        -> conn.cursor() puis cur.execute(...)
  - NOUVEAU : conn.rollback() dans les blocs except (Postgres abandonne
    la transaction en cours dès qu'une erreur survient, contrairement
    à SQLite).

CE QUI NE CHANGE PAS : tous les noms de fonctions, leurs signatures,
leurs valeurs de retour -- donc AUCUNE modification nécessaire côté
app.py (enregistrer_tour, charger_historique, effacer_conversation
gardent exactement le même contrat).

DÉPENDANCE D'ORDRE INCHANGÉE : create_table() ici pose une FOREIGN KEY
vers eleves(id) -- doit toujours être appelée APRÈS
create_table_eleves() au démarrage de app.py, comme c'était déjà le
cas avec SQLite.

PRINCIPE DE CONCEPTION D'ORIGINE (inchangé, décision du 02/09/2026) :
une conversation CONTINUE par couple (élève, matière) -- pas de liste
de conversations à gérer côté élève. Contrainte UNIQUE(eleve_id,
matiere) sur `conversations` -- impossible d'avoir deux conversations
actives pour la même matière du même élève.

ÉCRITURE : un message utilisateur ET la réponse complète de
l'assistant sont enregistrés ENSEMBLE, une fois la réponse
entièrement générée -- jamais pendant le streaming lui-même (voir
app.py: flux_evenements).

CHARGEMENT : charger_historique() ne renvoie QUE les tours déjà
enregistrés en base.
"""

import os
from typing import Optional

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "sur Render avec la chaine de connexion Postgres fournie par Neon "
        "-- sans elle, l'historique des conversations ne peut ni etre lu "
        "ni ecrit."
    )

ROLES_VALIDES = ('user', 'assistant')


def get_connection():
    """Retourne une connexion Postgres dont les curseurs renvoient des
    lignes de type dict (RealDictRow) -- même ergonomie que
    sqlite3.Row d'origine."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def create_table():
    """Idempotent comme les autres create_table() du projet -- appelée
    au démarrage de app.py, APRÈS create_table_eleves() (dépendance de
    clé étrangère eleve_id -> eleves.id), jamais destructive sur une
    table existante."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                eleve_id INTEGER NOT NULL,
                matiere TEXT NOT NULL,
                date_creation TEXT DEFAULT (NOW()::text),
                derniere_activite TEXT DEFAULT (NOW()::text),
                FOREIGN KEY (eleve_id) REFERENCES eleves(id)
            );
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_eleve_matiere
                ON conversations(eleve_id, matiere);
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages_conversation (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                contenu TEXT NOT NULL,
                date_creation TEXT DEFAULT (NOW()::text),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
                ON messages_conversation(conversation_id, date_creation);
        """)
        conn.commit()
    finally:
        conn.close()


def _obtenir_ou_creer_conversation(conn, eleve_id: int, matiere: str) -> int:
    """Retourne l'id de la conversation (eleve_id, matiere), la crée
    si elle n'existe pas encore. Fonction interne -- appelée sous une
    connexion déjà ouverte par l'appelant (enregistrer_tour), pas de
    connexion/fermeture propre ici pour rester dans la même
    transaction que l'insertion des messages qui suit.

    MIGRATION : cur.lastrowid n'existe pas en psycopg2 -- remplacé par
    une clause RETURNING id sur l'INSERT, lue via fetchone()."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM conversations WHERE eleve_id = %s AND matiere = %s",
        (eleve_id, matiere),
    )
    row = cur.fetchone()
    if row:
        return row['id']

    cur.execute(
        "INSERT INTO conversations (eleve_id, matiere) VALUES (%s, %s) RETURNING id",
        (eleve_id, matiere),
    )
    return cur.fetchone()['id']


def enregistrer_tour(eleve_id: int, matiere: str, question: str, reponse: str) -> None:
    """Enregistre un tour complet (question élève + réponse assistant)
    dans la conversation (eleve_id, matiere) -- la crée si c'est le
    premier message de cette matière pour cet élève.

    Appelée une seule fois, après que la réponse a été entièrement
    streamée à l'élève (voir app.py: flux_evenements, événement
    'fin') -- jamais avant.

    Ne lève pas d'exception vers l'appelant en cas d'échec -- une
    conversation non sauvegardée ne doit jamais empêcher l'élève de
    recevoir sa réponse, qui est déjà partie au moment où cette
    fonction est appelée."""
    if not question.strip() or not reponse.strip():
        return

    conn = get_connection()
    try:
        conversation_id = _obtenir_ou_creer_conversation(conn, eleve_id, matiere)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages_conversation (conversation_id, role, contenu) VALUES (%s, 'user', %s)",
            (conversation_id, question.strip()),
        )
        cur.execute(
            "INSERT INTO messages_conversation (conversation_id, role, contenu) VALUES (%s, 'assistant', %s)",
            (conversation_id, reponse.strip()),
        )
        cur.execute(
            "UPDATE conversations SET derniere_activite = NOW()::text WHERE id = %s",
            (conversation_id,),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"enregistrer_tour error: {e}")
    finally:
        conn.close()


def charger_historique(eleve_id: int, matiere: str, limite_tours: Optional[int] = None) -> list[dict]:
    """Retourne l'historique de la conversation (eleve_id, matiere)
    au format [{"role": "user"|"assistant", "content": "..."}],
    directement compatible avec le format déjà utilisé par
    chat_contexte.py et chat_llm_client.py.

    Retourne une liste vide si aucune conversation n'existe encore
    pour ce couple (élève, matière) -- cas normal, pas une erreur.

    `limite_tours` : si fourni, ne renvoie que les N derniers TOURS
    (1 tour = 1 message user + 1 message assistant). None = tout
    l'historique, sans troncature."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM conversations WHERE eleve_id = %s AND matiere = %s",
            (eleve_id, matiere),
        )
        conversation = cur.fetchone()
        if not conversation:
            return []

        limite_messages = limite_tours * 2 if limite_tours else None

        if limite_messages:
            # On veut les N DERNIERS tours mais dans l'ORDRE
            # chronologique -- récupérer les plus récents par DESC
            # puis inverser en Python est plus simple que de jouer
            # avec un ORDER BY + sous-requête pour un gain de
            # performance nul sur le volume attendu ici.
            cur.execute(
                """
                SELECT role, contenu FROM messages_conversation
                WHERE conversation_id = %s
                ORDER BY date_creation DESC, id DESC
                LIMIT %s
                """,
                (conversation['id'], limite_messages),
            )
            rows = list(reversed(cur.fetchall()))
        else:
            cur.execute(
                """
                SELECT role, contenu FROM messages_conversation
                WHERE conversation_id = %s
                ORDER BY date_creation ASC, id ASC
                """,
                (conversation['id'],),
            )
            rows = cur.fetchall()

        return [{"role": row["role"], "content": row["contenu"]} for row in rows]
    except Exception as e:
        print(f"charger_historique error: {e}")
        return []
    finally:
        conn.close()


def effacer_conversation(eleve_id: int, matiere: str) -> None:
    """Supprime définitivement la conversation (eleve_id, matiere) et
    tous ses messages -- vraie suppression (DELETE FROM), jamais de
    soft delete (un soft delete sur une conversation bloquerait la
    création d'une nouvelle conversation propre pour ce couple à
    cause de la contrainte UNIQUE(eleve_id, matiere))."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM conversations WHERE eleve_id = %s AND matiere = %s",
            (eleve_id, matiere),
        )
        conversation = cur.fetchone()
        if not conversation:
            return
        cur.execute("DELETE FROM messages_conversation WHERE conversation_id = %s", (conversation['id'],))
        cur.execute("DELETE FROM conversations WHERE id = %s", (conversation['id'],))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"effacer_conversation error: {e}")
    finally:
        conn.close()