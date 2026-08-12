# ExamensCam

Plateforme qui organise les annales officielles des examens nationaux camerounais (BEPC, Probatoire, BAC) par niveau, série et matière, pour les rendre accessibles et faciles à retrouver.

## Le problème

Les annales d'examens camerounais sont dispersées entre plusieurs sites, souvent mal classées, parfois filigranées ou difficiles à consulter. ExamensCam les rassemble à un seul endroit, organisées de façon cohérente avec le programme MINESEC réel (niveaux, séries, matières).

## Fonctionnalités (V1)

- Recherche par matière, niveau et série, avec reconnaissance d'alias et de fautes courantes (ex : "math", "bac c" → résultats pertinents)
- Navigation par niveau (BEPC, Probatoire, BAC) puis série puis matière
- Deux sources de contenu par matière :
  - **Énoncés officiels** — hébergés directement (PDF nettoyés, sans filigrane)
  - **Établissements** — épreuves indexées depuis des sites tiers, avec redirection vers la source
- Suivi anonyme des recherches et des pages consultées (aucune donnée personnelle), pour orienter les priorités de collecte

## Ce qui n'est pas encore là (prévu V2)

- Corrigés détaillés (en attente d'immatriculation RCCM, prévue décembre 2026)
- Paiement Mobile Money (CinetPay)
- Distinction visuelle entre épreuves zéro, harmonisées régionales et devoirs d'établissement

## Stack technique

- **Backend** : Python + Flask
- **Base de données** : SQLite, versionnée dans Git (persistance sur hébergement gratuit sans base externe)
- **PDF** : pikepdf, pypdf, pypdfium2, ReportLab, OpenCV (nettoyage de filigranes, génération)
- **Scraping** : requests + BeautifulSoup (sujetexa.com, mongosukulu.com)
- **Frontend** : HTML/Jinja2, CSS minimaliste, mobile-first
- **Hébergement** : Render.com

## Installation locale

\`\`\`bash
git clone <url-du-repo>
cd examenscam
pip install -r requirements.txt
python app.py
\`\`\`

L'application attend un fichier `data/annales.db` (SQLite) — déjà versionné dans le dépôt, aucune configuration supplémentaire nécessaire pour démarrer.

Variables d'environnement utilisées (optionnelles en local, à définir sur l'hébergement en production) :

\`\`\`
SECRET_KEY=
DEBUG=False
ADMIN_TOKEN=
\`\`\`

## Architecture

\`\`\`
app.py                     # Routes Flask, point d'entrée
database.py                # Accès table 'annales' (énoncés officiels)
database_externes.py       # Accès table 'annales_externes' (établissements)
database_carrefour.py      # Agrège les compteurs pour la page carrefour
database_matieres.py       # Liste des matières réellement présentes en base
database_search.py         # Scoring et alias de recherche
generer_search_index.py    # Reconstruit l'index de recherche après import
scripts/                   # Outils de collecte et d'import (scraping, CSV)
pdf_pipeline/               # Nettoyage de filigranes sur les PDF
templates/                  # Pages HTML (Jinja2)
static/                     # CSS
\`\`\`

## État du projet

En développement actif. Objectif : 500 épreuves officielles en base avant la rentrée de septembre 2026.

## Licence

Projet privé, tous droits réservés pour le moment.