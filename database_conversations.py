# database_conversations.py — ExamensCam
"""
Persistance des conversations du chat élève.

PRINCIPE DE CONCEPTION (décision du 02/09/2026) : une conversation
CONTINUE par couple (élève, matière) -- pas de liste de conversations
à gérer côté élève. La conversation de Mathématiques reste distincte
de celle de Physique, chacune se poursuit automatiquement à la
reconnexion, sans écran intermédiaire "choisis une conversation".

Contrainte UNIQUE(eleve_id, matiere) sur `conversations` -- impossible
d'avoir deux conversations actives pour la même matière du même
élève, donc pas d'ambiguïté sur laquelle charger à la reconnexion.

Même base que les élèves (data/annales.db) -- cohérent avec le
principe "SQLite + Git = persistance sur Render free tier" déjà en
place pour `eleves` (voir database_eleves.py) et `annales`. Une
jointure eleve_id reste triviale, pas de raison de fragmenter en
plusieurs fichiers .db.

ÉCRITURE : un message utilisateur ET la réponse complète de
l'assistant sont enregistrés ENSEMBLE, une fois la réponse
entièrement générée -- jamais pendant le streaming lui-même (voir
app.py: flux_evenements). Écrire à chaque morceau streamé
solliciterait SQLite bien plus que nécessaire pour un gain nul, la
persistance n'a de sens qu'une fois le tour de conversation complet.

CHARGEMENT : charger_historique() ne renvoie QUE les tours déjà
enregistrés en base -- ne préjuge pas de la limite d'historique à
transmettre au LLM (LIMITE_HISTORIQUE_TOURS reste géré côté app.py,
comme avant), cette fonction fournit la matière première brute.
"""

import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path('data') / 'annales.db'

ROLES_VALIDES = ('user', 'assistant')


def get_connection():
    Path('data').mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_table():
    """Idempotent comme les autres create_table() du projet -- appelée
    au démarrage de app.py, jamais destructive sur une table
    existante."""
    Path('data').mkdir(exist_ok=True)
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eleve_id INTEGER NOT NULL,
            matiere TEXT NOT NULL,
            date_creation TEXT DEFAULT (datetime('now')),
            derniere_activite TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (eleve_id) REFERENCES eleves(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_eleve_matiere
            ON conversations(eleve_id, matiere);

        CREATE TABLE IF NOT EXISTS messages_conversation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            contenu TEXT NOT NULL,
            date_creation TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
            ON messages_conversation(conversation_id, date_creation);
    """)
    conn.commit()
    conn.close()


def _obtenir_ou_creer_conversation(conn: sqlite3.Connection, eleve_id: int, matiere: str) -> int:
    """Retourne l'id de la conversation (eleve_id, matiere), la crée
    si elle n'existe pas encore. Fonction interne -- appelée sous une
    connexion déjà ouverte par l'appelant (enregistrer_tour), pas de
    connexion/fermeture propre ici pour rester dans la même
    transaction que l'insertion des messages qui suit."""
    row = conn.execute(
        "SELECT id FROM conversations WHERE eleve_id = ? AND matiere = ?",
        (eleve_id, matiere),
    ).fetchone()
    if row:
        return row['id']

    cur = conn.execute(
        "INSERT INTO conversations (eleve_id, matiere) VALUES (?, ?)",
        (eleve_id, matiere),
    )
    return cur.lastrowid


def enregistrer_tour(eleve_id: int, matiere: str, question: str, reponse: str) -> None:
    """Enregistre un tour complet (question élève + réponse assistant)
    dans la conversation (eleve_id, matiere) -- la crée si c'est le
    premier message de cette matière pour cet élève.

    Appelée une seule fois, après que la réponse a été entièrement
    streamée à l'élève (voir app.py: flux_evenements, événement
    'fin') -- jamais avant, sinon un message assistant vide ou
    partiel serait enregistré si le stream échoue en cours de route.

    Ne lève pas d'exception vers l'appelant en cas d'échec -- une
    conversation non sauvegardée ne doit jamais empêcher l'élève de
    recevoir sa réponse, qui est déjà partie au moment où cette
    fonction est appelée. Le même principe de tolérance que
    incrementer_usage_mensuel() dans database_eleves.py."""
    if not question.strip() or not reponse.strip():
        return

    conn = get_connection()
    try:
        conversation_id = _obtenir_ou_creer_conversation(conn, eleve_id, matiere)
        conn.execute(
            "INSERT INTO messages_conversation (conversation_id, role, contenu) VALUES (?, 'user', ?)",
            (conversation_id, question.strip()),
        )
        conn.execute(
            "INSERT INTO messages_conversation (conversation_id, role, contenu) VALUES (?, 'assistant', ?)",
            (conversation_id, reponse.strip()),
        )
        conn.execute(
            "UPDATE conversations SET derniere_activite = datetime('now') WHERE id = ?",
            (conversation_id,),
        )
        conn.commit()
    except Exception as e:
        print(f"enregistrer_tour error: {e}")
    finally:
        conn.close()


def charger_historique(eleve_id: int, matiere: str, limite_tours: Optional[int] = None) -> list[dict]:
    """Retourne l'historique de la conversation (eleve_id, matiere)
    au format [{"role": "user"|"assistant", "content": "..."}],
    directement compatible avec le format déjà utilisé par
    chat_contexte.py et chat_llm_client.py -- aucune conversion
    nécessaire côté appelant.

    Retourne une liste vide si aucune conversation n'existe encore
    pour ce couple (élève, matière) -- cas normal du tout premier
    message, pas une erreur.

    `limite_tours` : si fourni, ne renvoie que les N derniers TOURS
    (1 tour = 1 message user + 1 message assistant), pas les N
    derniers messages bruts -- pour rester cohérent avec
    LIMITE_HISTORIQUE_TOURS déjà utilisé côté app.py. None = tout
    l'historique, sans troncature (l'appelant applique sa propre
    limite ensuite si besoin)."""
    conn = get_connection()
    try:
        conversation = conn.execute(
            "SELECT id FROM conversations WHERE eleve_id = ? AND matiere = ?",
            (eleve_id, matiere),
        ).fetchone()
        if not conversation:
            return []

        limite_messages = limite_tours * 2 if limite_tours else None

        if limite_messages:
            # On veut les N DERNIERS tours mais dans l'ORDRE
            # chronologique -- récupérer les plus récents par DESC
            # puis inverser en Python est plus simple que de jouer
            # avec un ORDER BY + sous-requête pour un gain de
            # performance nul sur le volume attendu ici (une
            # conversation élève, pas des millions de lignes).
            rows = conn.execute(
                """
                SELECT role, contenu FROM messages_conversation
                WHERE conversation_id = ?
                ORDER BY date_creation DESC, id DESC
                LIMIT ?
                """,
                (conversation['id'], limite_messages),
            ).fetchall()
            rows = list(reversed(rows))
        else:
            rows = conn.execute(
                """
                SELECT role, contenu FROM messages_conversation
                WHERE conversation_id = ?
                ORDER BY date_creation ASC, id ASC
                """,
                (conversation['id'],),
            ).fetchall()

        return [{"role": row["role"], "content": row["contenu"]} for row in rows]
    except Exception as e:
        print(f"charger_historique error: {e}")
        return []
    finally:
        conn.close()


def effacer_conversation(eleve_id: int, matiere: str) -> None:
    """Supprime définitivement la conversation (eleve_id, matiere) et
    tous ses messages -- vraie suppression (DELETE FROM), jamais de
    soft delete (voir leçon actif=0 dans la doc du projet : un soft
    delete sur une conversation bloquerait la création d'une nouvelle
    conversation propre pour ce couple à cause de la contrainte
    UNIQUE(eleve_id, matiere))."""
    conn = get_connection()
    try:
        conversation = conn.execute(
            "SELECT id FROM conversations WHERE eleve_id = ? AND matiere = ?",
            (eleve_id, matiere),
        ).fetchone()
        if not conversation:
            return
        conn.execute("DELETE FROM messages_conversation WHERE conversation_id = ?", (conversation['id'],))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation['id'],))
        conn.commit()
    except Exception as e:
        print(f"effacer_conversation error: {e}")
    finally:
        conn.close()