# ExamensCam

Plateforme qui organise les annales officielles des examens nationaux camerounais (BEPC, Probatoire, BAC) par niveau, serie et matiere.

## Le probleme

Les annales d'examens camerounais sont dispersees entre plusieurs sites, souvent mal classees ou difficiles a consulter. ExamensCam les rassemble a un seul endroit, organisees selon le programme MINESEC reel.

## Fonctionnalites

- Recherche par matiere, niveau et serie, avec reconnaissance d'alias et de fautes courantes
- Navigation par niveau (BEPC, Probatoire, BAC), puis serie, puis matiere
- Deux sources de contenu par matiere :
  - Enonces officiels, heberges directement, PDF nettoyes
  - Etablissements, epreuves indexees depuis des sites tiers, avec redirection vers la source
- Suivi anonyme des recherches et des pages consultees, sans donnee personnelle, pour orienter les priorites de collecte

## Stack technique

- Backend : Python et Flask
- Base de donnees : SQLite, versionnee dans Git
- PDF : pikepdf, pypdf, pypdfium2, ReportLab, OpenCV
- Scraping : requests et BeautifulSoup
- Frontend : HTML, Jinja2, CSS
- Hebergement : Render.com

## Installation locale

```bash
git clone <url-du-repo>
cd examenscam
pip install -r requirements.txt
python app.py
```

Le fichier `data/annales.db` est deja versionne dans le depot, aucune configuration supplementaire n'est necessaire pour demarrer.

Variables d'environnement utilisees :

```
SECRET_KEY=
DEBUG=False
ADMIN_TOKEN=
```

## Architecture

```
app.py                     Routes Flask, point d'entree
database.py                Acces table annales, enonces officiels
database_externes.py       Acces table annales_externes, etablissements
database_carrefour.py      Compteurs pour la page carrefour
database_matieres.py       Matieres reellement presentes en base
database_search.py         Scoring et alias de recherche
generer_search_index.py    Reconstruit l'index de recherche
scripts/                   Outils de collecte et d'import
pdf_pipeline/               Nettoyage des PDF
templates/                  Pages HTML
static/                     CSS
```

## Etat du projet

En developpement actif.

## Licence

Projet prive, tous droits reserves pour le moment.