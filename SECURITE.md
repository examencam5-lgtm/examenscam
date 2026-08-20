# Securite ExamensCam

Ce document trace les audits de securite que je mene sur ce projet. Chaque entree liste ce que j'ai verifie, comment, et le resultat. Le but est simple : pouvoir prouver a tout moment ce qui a ete controle, pas seulement affirmer que "c'est securise".

## Pourquoi ce document existe

Un projet solo construit sur plusieurs mois n'a de valeur professionnelle que si chaque decision de securite est tracable. Ce document distingue un projet pilote serieusement d'un empilement de fonctionnalites sans controle. Il me sert aussi de guide personnel : quand j'ajoute une fonctionnalite, je reviens ici verifier que je n'ai rien oublie des reflexes de base.

---

## Audit du 20 aout 2026

Perimetre controle : les routes principales de l'application, les fonctions d'acces a la base de donnees, le systeme d'analytics interne, le formulaire de connexion admin, la recherche, les pages d'erreur, et les dependances du projet.

Methode : chaque correction a ete testee reellement avant d'etre integree, pas seulement relue.

### 1. Secrets et historique du depot

Probleme trouve : des valeurs de secours pour les cles de securite etaient ecrites directement dans le code, visibles dans plusieurs versions passees du depot.

Correction :
- Suppression de ces valeurs de secours. L'application refuse maintenant de demarrer si les cles necessaires ne sont pas correctement configurees.
- Changement complet des cles concernees.
- Nettoyage de l'historique du depot Git, avec verification que les anciennes valeurs n'apparaissent plus nulle part, y compris apres un clonage neuf du depot.

Statut : resolu et verifie.

### 2. Injection SQL

Fichiers controles : toutes les fonctions d'acces a la base de donnees (recherche, catalogue de matieres, epreuves d'etablissements, statistiques).

Methode : verification ligne par ligne que toute valeur venant d'un visiteur passe uniquement par des parametres lies, jamais par assemblage direct de texte dans une requete.

Statut : aucune faille trouvee.

### 3. Failles d'affichage (XSS)

Faille trouvee : la barre de recherche inserait certains resultats directement dans la page sans les neutraliser au prealable. Comme une partie du contenu affiche provient de sources externes non controlees, un contenu malveillant aurait pu s'executer dans le navigateur d'un visiteur.

Correction : chaque element affiche par la recherche est desormais systematiquement neutralise avant insertion dans la page, et les liens sont verifies pour exclure tout format dangereux.

Verifie : test avec un contenu malveillant simule, confirmation qu'il s'affiche comme texte inoffensif et ne s'execute jamais.

Statut : corrige et verifie.

### 4. Fuites d'information en cas d'erreur

Correction : ajout d'une page d'erreur generique pour les problemes serveur imprevus, sans aucun detail technique visible. Les erreurs completes restent enregistrees uniquement dans les journaux internes, jamais montrees au visiteur.

Verifie : simulation d'un plantage contenant une information sensible, confirmation qu'elle n'apparait jamais dans la reponse envoyee au visiteur.

Statut : corrige et verifie.

### 5. Cookies de session

Correction : le cookie qui atteste de la connexion administrateur est desormais configure pour n'etre transmis que sur une connexion chiffree, inaccessible depuis un script, et protege contre l'envoi depuis un autre site.

Verifie : inspection directe des en-tetes envoyes par le serveur, confirmation des trois protections actives en conditions reelles.

Statut : corrige et verifie.

### 6. Dependances du projet

Probleme trouve : aucune version des bibliotheques utilisees n'etait fixee, ce qui signifie qu'une version differente pouvait etre installee a chaque mise en ligne sans controle.

Correction : toutes les versions sont desormais fixees precisement et ont ete verifiees contre les vulnerabilites connues au moment de l'audit. Aucune vulnerabilite trouvee.

Procedure a suivre pour toute mise a jour future : verifier chaque nouvelle version contre les vulnerabilites connues avant de l'adopter, jamais a l'aveugle.

Statut : corrige et verifie. Necessite une revue reguliere.

### 7. Protection contre la surcharge

Probleme trouve : la recherche et l'enregistrement des clics n'avaient aucune limite de frequence, exposant le service a une saturation en cas d'usage abusif ou automatise.

Correction : mise en place d'une limite de requetes par visiteur sur ces deux fonctions.

Verifie : confirmation qu'un usage normal n'est jamais bloque, qu'un usage abusif l'est, et que chaque visiteur est traite independamment.

Statut : corrige et verifie.

### 8. Exposition publique du depot

Voir point 1. Le fichier d'exclusion Git a egalement ete controle et corrige apres un probleme d'encodage qui l'empechait de fonctionner correctement.

Statut : resolu.

### 9. Falsification de requete entre sites (CSRF)

Correction : le formulaire de connexion administrateur exige desormais un jeton de securite unique, genere a chaque affichage et verifie a la soumission, empechant qu'une page exterieure ne force une connexion a mon insu.

Verifie : cinq scenarios testes, dont une simulation directe de ce type d'attaque, confirmant le rejet systematique sans le bon jeton.

Statut : corrige et verifie.

Perimetre actuel : seule action administrateur sensible existant a ce jour. A reappliquer si de nouvelles actions sont ajoutees au tableau de bord.

### 10. Redirection non controlee

Analyse : la route de redirection vers les sources externes recupere toujours sa destination depuis la base de donnees a partir d'un identifiant numerique, jamais depuis une valeur fournie directement par le visiteur.

Verifie : tentative d'injection d'une adresse dans l'URL et via un parametre, toutes deux sans effet.

Statut : aucune faille exploitable trouvee.

---

## Ce qui reste a controler

Points identifies mais non couverts par l'audit du 20 aout 2026, par ordre de priorite :

1. Validation des adresses collectees automatiquement depuis des sources externes avant leur enregistrement en base. Une source compromise ou modifiee pourrait faire enregistrer une adresse non fiable, que le site redirigerait ensuite en toute confiance.
2. Audit du pipeline de traitement des fichiers PDF et des scripts de collecte automatisee eux-memes.
3. Fermeture systematique des connexions a la base de donnees en cas d'erreur imprevue dans certaines fonctions, pour eviter une accumulation sur le long terme.
4. Aucun scan automatise exhaustif n'a ete effectue, seulement un controle manuel raisonne.
5. Verifier regulierement que la mise en ligne automatique depuis le depot fonctionne toujours, ce lien s'etant deja rompu une fois par le passe.

## Ce qu'il reste a rediger, au dela du code

- Politique de confidentialite : quelles donnees sont collectees, combien de temps conservees, qui y a acces.
- Conditions d'utilisation completes, tenant compte de l'absence de compte utilisateur et du fait qu'aucune donnee personnelle identifiante n'est collectee a ce jour.

---

## Historique des audits

| Date | Perimetre | Points traites |
|---|---|---|
| 20 aout 2026 | Securite applicative complete | Secrets, injection SQL, failles d'affichage, fuites d'erreur, cookies de session, dependances, protection contre la surcharge, exposition du depot, falsification de requete, redirection non controlee |

Chaque nouvel audit doit ajouter une ligne ici, avec la date, le perimetre controle, et ce qui a ete verifie.