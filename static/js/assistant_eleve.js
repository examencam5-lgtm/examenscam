(function () {
  'use strict';

  const fenetre = document.getElementById('assistant-fenetre');
  const saisie = document.getElementById('assistant-saisie');
  const sidebar = document.getElementById('assistant-sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');

  const form = document.getElementById('form-saisie');
  const input = document.getElementById('input-question');
  const btnEnvoyer = document.getElementById('btn-envoyer');

  const btnAjouter = document.getElementById('btn-ajouter');
  const panneauAjouter = document.getElementById('panneau-ajouter');
  const btnAjouterEpreuve = document.getElementById('btn-ajouter-epreuve');

  const btnHeaderMenu = document.getElementById('btn-header-menu');
  const btnSidebarToggleMobile =
    document.getElementById('btn-sidebar-toggle-mobile');

  const btnNouvelleConversation =
    document.getElementById('btn-nouvelle-conversation');

  const btnSidebarExamen =
    document.getElementById('btn-sidebar-examen');

  const btnSidebarSequence =
    document.getElementById('btn-sidebar-sequence');

  const btnSidebarParcourir =
    document.getElementById('btn-sidebar-parcourir');

  const MODE_DEMO = window.APP_CONFIG.modeDemo;

  const ELEVE = window.APP_CONFIG.eleve;

  const MATIERES_DISPO = window.APP_CONFIG.matieresDispo;

  // Contrôleur d'abandon de la requête en cours (null = rien à interrompre)
  let controleurAbandon = null;

  const ICONE_ENVOYER =
    '<path d="M4 4l16 8-16 8 3-8z"/><path d="M7 12h13"/>';

  const ICONE_STOP =
    '<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none"/>';

  const etat = {
    enAttente: false,
    panneauOuvert: false,
    matiere: null,
    chargementHistorique: false,
    suivreDefilement: true
  };

  const SERIE_GENERATION_DISPONIBLE = 'C';

  if (
    Array.isArray(MATIERES_DISPO) &&
    MATIERES_DISPO.length
  ) {
    etat.matiere =
      MATIERES_DISPO.includes('Mathematiques')
        ? 'Mathematiques'
        : MATIERES_DISPO[0];
  }

  // L'utilisateur est-il déjà proche du bas de la fenêtre ?
  // Sert à décider si on continue de suivre le flux ou si on le laisse lire tranquille.
  function estAncreEnBas() {
    if (!fenetre) return true;
    return (
      fenetre.scrollHeight -
        fenetre.scrollTop -
        fenetre.clientHeight 
      60
    );
  }

  function basculerBoutonEnvoyer(mode) {
    if (!btnEnvoyer) return;

    const svg = btnEnvoyer.querySelector('svg');

    if (mode === 'stop') {
      btnEnvoyer.classList.add('btn-envoyer--stop');
      btnEnvoyer.setAttribute(
        'aria-label',
        'Interrompre la génération'
      );
      btnEnvoyer.disabled = false;

      if (svg) svg.innerHTML = ICONE_STOP;
    } else {
      btnEnvoyer.classList.remove('btn-envoyer--stop');
      btnEnvoyer.setAttribute('aria-label', 'Envoyer');

      if (svg) svg.innerHTML = ICONE_ENVOYER;

      synchroniserEtatEnvoi();
    }
  }

  function interrompreGeneration() {
    if (controleurAbandon) {
      controleurAbandon.abort();
    }
  }

  function genererMessageAccueil() {
    if (MODE_DEMO) {
      return 'Bienvenue dans ton espace ExamensCam. Connecte-toi pour accéder aux annales officielles de ton niveau, générer des épreuves d’entraînement et poser tes questions.';
    }

    if (!etat.matiere) {
      return `Bonjour ${ELEVE.prenom}. Ton espace ${ELEVE.niveau}${ELEVE.serie ? ' ' + ELEVE.serie : ''} arrive bientôt. En attendant, tu peux déjà parcourir les épreuves indexées des lycées et collèges.`;
    }

    return `Bonjour ${ELEVE.prenom}. Tu travailles actuellement en ${etat.matiere}, ${ELEVE.niveau}${ELEVE.serie ? ' ' + ELEVE.serie : ''}.`;
  }

  function afficherAccueil() {
    if (!fenetre) return;

    fenetre.classList.add('mode-accueil');

    const accueil = document.createElement('section');
    accueil.className = 'assistant-welcome centree';
    accueil.id = 'assistant-welcome';

    const kicker = document.createElement('div');
    kicker.className = 'welcome-kicker';
    kicker.textContent = etat.matiere || 'Accompagnement scolaire';

    const titre = document.createElement('h2');
    titre.className = 'welcome-title';
    titre.textContent = `Bonjour ${ELEVE.prenom}.`;

    const contexte = document.createElement('p');
    contexte.className = 'welcome-context';

    const messageAccueil = genererMessageAccueil();

    contexte.textContent =
      messageAccueil.replace(
        `Bonjour ${ELEVE.prenom}. `,
        ''
      );

    const question = document.createElement('p');
    question.className = 'welcome-question';
    question.textContent = 'Que veux-tu faire ?';

    let btnConnexionAccueil = null;

    if (MODE_DEMO) {
      btnConnexionAccueil =
        document.createElement('a');

      btnConnexionAccueil.href =
        window.APP_URLS.connexionGoogle;

      btnConnexionAccueil.className =
        'welcome-connexion-btn';

      btnConnexionAccueil.innerHTML =
        '<span>Se connecter avec Google</span>' +
        '<svg viewBox="0 0 24 24" aria-hidden="true">' +
        '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>' +
        '</svg>';
    }

    const actions = document.createElement('div');
    actions.className = 'welcome-actions';

    const creerAction = (
      label,
      action,
      svgPath,
      desactivee
    ) => {
      const bouton = document.createElement('button');

      bouton.type = 'button';
      bouton.className = 'welcome-action';

      const texte = document.createElement('span');
      texte.textContent = label;

      const icone = document.createElement('svg');
      icone.setAttribute('viewBox', '0 0 24 24');
      icone.setAttribute('aria-hidden', 'true');
      icone.innerHTML = svgPath;

      bouton.append(texte, icone);

      if (desactivee) {
        bouton.disabled = true;
        bouton.title =
          MODE_DEMO
            ? 'Connecte-toi pour accéder à cette fonctionnalité'
            : 'Bientôt disponible pour ta série';
      } else {
        bouton.addEventListener('click', action);
      }

      actions.appendChild(bouton);
    };

    creerAction(
      'Chercher un exercice officiel',
      () => {
        fermerSidebar();
        ouvrirPanneauVide();
        afficherChoixAnneeExerciceOfficiel();
      },
      '<path d="M11 4a7 7 0 1 0 4.9 12l4.6 4.6"/><path d="M9 11h4M11 9v4"/>',
      !ELEVE.niveau
    );

    creerAction(
      'Générer un examen officiel (Bac blanc)',
      () => {
        lancerGeneration(
          {
            type_document: 'Examen',
            serie: SERIE_GENERATION_DISPONIBLE
          },
          'Génère-moi un Examen officiel (Bac blanc)'
        );
      },
      '<path d="M4 19.5V6.8a1.8 1.8 0 0 1 1.8-1.8h12.4A1.8 1.8 0 0 1 20 6.8v12.7"/><path d="M4 18.5c1.2-.8 2.7-1.1 4.2-.8l3.8.8 3.8-.8c1.5-.3 3 0 4.2.8"/>',
      MODE_DEMO || !ELEVE.disponible
    );

    creerAction(
      'Générer une épreuve de séquence',
      () => {
        fermerSidebar();
        ouvrirPanneauVide();
        afficherChoixSequence();
      },
      '<path d="M5 4h10l4 4v12H5z"/><path d="M15 4v5h4M8 13h8M8 16h6"/>',
      MODE_DEMO || !ELEVE.disponible
    );

    creerAction(
      'Parcourir les épreuves indexées',
      () => {
        fermerSidebar();
        ouvrirPanneauVide();

        if (!MODE_DEMO && ELEVE.niveau) {
          afficherChoixMatiere(
            ELEVE.niveau,
            ELEVE.serie || null
          );
        } else {
          afficherChoixNiveau();
        }
      },
      '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21z"/><path d="M4 5.5v15M8 7h8M8 10h6"/>',
      false
    );

    const note = document.createElement('p');
    note.className = 'welcome-note';
    note.textContent =
      'Annales officielles indexées par lycée et collège. Les épreuves générées suivent le programme et le barème réels de ta série.';

    accueil.append(
      kicker,
      titre,
      contexte
    );

    if (btnConnexionAccueil) {
      accueil.append(btnConnexionAccueil);
    }

    accueil.append(
      question,
      actions,
      note
    );

    fenetre.appendChild(accueil);
  }

  function masquerAccueil() {
    const accueil =
      document.getElementById('assistant-welcome');

    if (accueil) {
      accueil.remove();
    }

    if (fenetre) {
      fenetre.classList.remove('mode-accueil');
    }
  }

  function commencerAvecTexte(texte) {
    masquerAccueil();

    if (!input) {
      return;
    }

    input.value = texte;
    input.focus();

    input.dispatchEvent(
      new Event('input', {
        bubbles: true
      })
    );
  }

  function structurerTexteExercice(texte) {
    let resultat = texte;

    resultat = resultat.replace(/\\n/g, '\n\n');

    resultat = resultat.replace(
      /^[ \t]*(EXERCICE|Exercice)\s+([^\n]{0,80})/gm,
      (match, mot, reste) => `\n\n### MARQUEUREXO ${mot} ${reste.trim()}\n\n`
    );

    resultat = resultat.replace(
      /^[ \t]*(PARTIE|Partie)\s+([^\n]{0,80})/gm,
      (match, mot, reste) => `\n\n#### MARQUEURPARTIE ${mot} ${reste.trim()}\n\n`
    );

    resultat = resultat.replace(
      /^[ \t]*(\d{1,2}\.\s[^\n]{1,90}?\/\s*\d+(?:,\d+)?\s*points?)[ \t]*$/gim,
      (match, titre) => `\n\n### MARQUEURSOUS ${titre}\n\n`
    );

    resultat = resultat.replace(
      /(\d{1,2})\.(?=\s+(?:[A-ZÉÈÀÂÎ]|[a-e]\)))/g,
      (match, numero) => `\n\n<span class="numero-question">${numero}.</span>`
    );

    resultat = resultat.replace(
      /\(?([a-e])\)(?=\s+\S)/g,
      (match, lettre) => `\n\nMARQUEURLETTRE<span class="numero-question">${lettre})</span>`
    );

    resultat = resultat.replace(
      /(\/\s*\d+(?:,\d+)?\s*points?)\s+(?=[A-ZÉÈÀÂÎ])/g,
      '$1\n\n'
    );

    resultat = resultat.replace(/\n{3,}/g, '\n\n');
    resultat = resultat.replace(/^\n+/, '');

    return resultat;
  }
  function rendreReponseAssistant(conteneur, texte) {
    if (!conteneur) return;

    const texteSecurise =
      typeof texte === 'string'
        ? texte
        : String(texte || '');

    const blocsLatex = [];

    const texteProtege = texteSecurise.replace(
      /\$\$[\s\S]+?\$\$|\$[^$\n]+?\$/g,
      (match) => {
        const jeton = `@@LATEX${blocsLatex.length}@@`;
        blocsLatex.push(match);
        return jeton;
      }
    );

    const texteStructure = structurerTexteExercice(texteProtege);

    let html = marked.parse(texteStructure);

    html = html.replace(
      /<h3>MARQUEUREXO ([\s\S]*?)<\/h3>/g,
      '<h3 class="titre-exercice">$1</h3>'
    );
    html = html.replace(
      /<h4>MARQUEURPARTIE ([\s\S]*?)<\/h4>/g,
      '<h4 class="titre-partie">$1</h4>'
    );
    html = html.replace(
      /<h3>MARQUEURSOUS ([\s\S]*?)<\/h3>/g,
      '<h3 class="titre-sous-partie">$1</h3>'
    );

    html = html.replace(
      /<p>MARQUEURLETTRE/g,
      '<p class="sous-question">'
    );

    blocsLatex.forEach((bloc, i) => {
      html = html.split(`@@LATEX${i}@@`).join(bloc);
    });

    conteneur.innerHTML =
      window.DOMPurify
        ? DOMPurify.sanitize(html, { ADD_ATTR: ['class'] })
        : html;

    if (window.renderMathInElement) {
      renderMathInElement(conteneur, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '$', right: '$', display: false }
        ],
        throwOnError: false
      });
    }
  }
  function ajouterMessageUtilisateur(texte) {
    if (!fenetre) return;

    fenetre.classList.remove('mode-accueil');

    const ligne = document.createElement('div');
    ligne.className = 'msg msg-user';

    const bulle = document.createElement('div');
    bulle.className = 'msg-user-bulle';
    bulle.textContent = texte;

    ligne.appendChild(bulle);
    fenetre.appendChild(ligne);

    // On place le début de l'échange en haut du viewport plutôt que de
    // sauter directement au bas de la fenêtre : c'est ce qui laisse la
    // place de lire la réponse depuis son début pendant qu'elle arrive.
    requestAnimationFrame(() => {
      ligne.scrollIntoView({
        block: 'start',
        behavior: 'smooth'
      });
    });
  }

  function ajouterMessageAssistant(
    texte,
    enAttente
  ) {
    if (!fenetre) return null;

    const ligne = document.createElement('div');

    ligne.className =
      'msg msg-bot' +
      (enAttente ? ' msg-attente' : '');

    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.textContent = '';

    const corps = document.createElement('div');
    corps.className = 'msg-bot-corps';

    if (enAttente) {
      corps.innerHTML = `
        <div class="indicateur-reflexion">
          <div class="points-typing">
            <span></span>
            <span></span>
            <span></span>
          </div>
          <span class="texte-progression">
            Je réfléchis...
          </span>
        </div>
      `;

      const phrases = [
        'Je réfléchis...',
        'Je vérifie le calcul...',
        'Je prépare la réponse...'
      ];

      let i = 0;

      const spanTexte =
        corps.querySelector(
          '.texte-progression'
        );

      ligne._intervalReflexion =
        setInterval(() => {
          if (!spanTexte) return;

          i = (i + 1) % phrases.length;

          spanTexte.style.animation = 'none';

          void spanTexte.offsetHeight;

          spanTexte.textContent = phrases[i];
          spanTexte.style.animation =
            'fondu 0.3s ease';

        }, 2200);

    } else {
      rendreReponseAssistant(
        corps,
        texte
      );
    }

    ligne.appendChild(avatar);
    ligne.appendChild(corps);
    fenetre.appendChild(ligne);

    if (estAncreEnBas()) {
      fenetre.scrollTop = fenetre.scrollHeight;
    }

    return ligne;
  }

  function retirerLigneAttente(ligne) {
    if (!ligne) return;

    if (ligne._intervalReflexion) {
      clearInterval(
        ligne._intervalReflexion
      );

      ligne._intervalReflexion = null;
    }

    ligne.remove();
  }

  function ajouterCarteResultats(
    intro,
    resultats
  ) {
    if (!fenetre) return null;

    const ligne = document.createElement('div');
    ligne.className = 'msg msg-bot';

    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.textContent = '';

    const corps = document.createElement('div');
    corps.className = 'msg-bot-corps';

    const p = document.createElement('p');
    p.textContent = intro;

    corps.appendChild(p);

    const liste = document.createElement('div');
    liste.className = 'liste-resultats';

    if (Array.isArray(resultats)) {
      resultats.forEach((r) => {
        if (!r || !r.destination) {
          return;
        }

        const carte = document.createElement('a');

        carte.className =
          'carte-resultat';

        carte.href =
          r.destination;

        const titre =
          document.createElement('span');

        titre.className =
          'carte-resultat-titre';

        titre.textContent =
          r.libelle || 'Épreuve';

        const badge =
          document.createElement('span');

        const estOfficiel =
          r.type_source === 'officiel';

        badge.className =
          'carte-resultat-badge ' +
          (
            estOfficiel
              ? 'officiel'
              : 'externe'
          );

        badge.textContent =
          estOfficiel
            ? 'Officiel'
            : 'Externe';

        carte.appendChild(titre);
        carte.appendChild(badge);

        liste.appendChild(carte);
      });
    }

    corps.appendChild(liste);

    ligne.appendChild(avatar);
    ligne.appendChild(corps);

    fenetre.appendChild(ligne);

    fenetre.scrollTop =
      fenetre.scrollHeight;

    return ligne;
  }

  async function chargerEtAfficherHistorique() {
    if (!fenetre) return;

    fenetre.innerHTML = '';

    if (
      MODE_DEMO ||
      !etat.matiere
    ) {
      afficherAccueil();
      return;
    }

    etat.chargementHistorique = true;

    try {
      const params =
        new URLSearchParams({
          matiere: etat.matiere
        });

      const reponseServeur =
        await fetch(
          `${window.APP_URLS.historique}?${params}`,
          {
            headers: {
              'Accept': 'application/json'
            }
          }
        );

      if (!reponseServeur.ok) {
        throw new Error(
          'Historique indisponible'
        );
      }

      const donnees =
        await reponseServeur.json();

      const historique =
        donnees.historique;

      if (
        !Array.isArray(historique) ||
        historique.length === 0
      ) {
        afficherAccueil();
        return;
      }

      fenetre.classList.remove(
        'mode-accueil'
      );

      historique.forEach((tour) => {
        if (!tour) return;

        if (tour.role === 'user') {
          ajouterMessageUtilisateur(
            tour.content || ''
          );
        } else {
          ajouterMessageAssistant(
            tour.content || '',
            false
          );
        }
      });

    } catch (erreur) {
      console.error(
        'Erreur historique :',
        erreur
      );

      fenetre.innerHTML = '';
      afficherAccueil();

    } finally {
      etat.chargementHistorique = false;
    }
  }

  async function envoyerMessage(texte) {
    if (
      !texte ||
      etat.enAttente
    ) {
      return;
    }

    masquerAccueil();
    fermerPanneauAjouter();

    ajouterMessageUtilisateur(
      texte
    );

    etat.enAttente = true;
    etat.suivreDefilement = true;

    basculerBoutonEnvoyer('stop');

    const ligneAttente =
      ajouterMessageAssistant(
        '',
        true
      );

    // Références partagées entre le bloc try et le catch (abandon possible
    // à tout moment : avant, pendant ou après le début du streaming).
    let corpsFlux = null;
    let curseurFlux = null;
    let texteAccumule = '';
    let erreurRecue = null;

    controleurAbandon = new AbortController();

    try {
      const reponseServeur =
        await fetch(
          window.APP_URLS.repondre,
          {
            method: 'POST',
            headers: {
              'Content-Type':
                'application/json',
              'Accept':
                'text/event-stream, application/json'
            },
            body: JSON.stringify({
              question: texte,
              niveau: ELEVE.niveau,
              serie: ELEVE.serie,
              matiere: etat.matiere
            }),
            signal: controleurAbandon.signal
          }
        );

      const typeContenu =
        reponseServeur.headers
          .get('Content-Type') || '';

      if (
        !typeContenu.includes(
          'text/event-stream'
        )
      ) {
        let resultat;

        try {
          resultat =
            await reponseServeur.json();
        } catch {
          throw new Error(
            'Le serveur a renvoyé une réponse invalide.'
          );
        }

        retirerLigneAttente(
          ligneAttente
        );

        if (!reponseServeur.ok) {
          throw new Error(
            resultat.erreur ||
            'Une erreur est survenue.'
          );
        }

        if (
          resultat.type ===
          'resultats'
        ) {
          ajouterCarteResultats(
            resultat.intro ||
              'Voici ce que j’ai trouvé :',
            resultat.resultats || []
          );
        } else {
          ajouterMessageAssistant(
            resultat.reponse ||
              "Je n’ai pas reçu de réponse.",
            false
          );
        }

        return;
      }

      if (!reponseServeur.body) {
        throw new Error(
          'Le serveur n’a fourni aucun flux de réponse.'
        );
      }

      if (
        ligneAttente &&
        ligneAttente._intervalReflexion
      ) {
        clearInterval(
          ligneAttente._intervalReflexion
        );

        ligneAttente._intervalReflexion =
          null;
      }

      ligneAttente.classList.remove(
        'msg-attente'
      );

      corpsFlux =
        ligneAttente.querySelector(
          '.msg-bot-corps'
        );

      if (!corpsFlux) {
        throw new Error(
          'Conteneur de réponse introuvable.'
        );
      }

      corpsFlux.innerHTML = '';

      curseurFlux =
        document.createElement('span');

      curseurFlux.className =
        'curseur-streaming';

      corpsFlux.appendChild(curseurFlux);

      const lecteur =
        reponseServeur.body.getReader();

      const decodeur =
        new TextDecoder();

      let tampon = '';

      function traiterEvenementSSE(
        evenementBrut
      ) {
        if (
          !evenementBrut ||
          !evenementBrut.startsWith(
            'data: '
          )
        ) {
          return;
        }

        const contenu =
          evenementBrut.slice(6).trim();

        if (!contenu) return;

        let evenement;

        try {
          evenement =
            JSON.parse(contenu);
        } catch (erreur) {
          console.error(
            'Événement SSE invalide :',
            contenu,
            erreur
          );
          return;
        }

        if (
          evenement.type ===
          'morceau'
        ) {
          texteAccumule +=
            evenement.texte || '';

          corpsFlux.textContent =
            texteAccumule;

          corpsFlux.appendChild(
            curseurFlux
          );

          // On ne force le défilement que si l'utilisateur suit déjà
          // le bas de la conversation -- sinon on le laisse lire en paix.
          if (etat.suivreDefilement) {
            fenetre.scrollTop =
              fenetre.scrollHeight;
          }

        } else if (
          evenement.type ===
          'erreur'
        ) {
          erreurRecue =
            evenement.texte ||
            'Une erreur est survenue.';

        } else if (
          evenement.type ===
          'fin'
        ) {
          if (
            typeof evenement.texte_complet ===
            'string'
          ) {
            texteAccumule =
              evenement.texte_complet;
          }
        }
      }

      while (true) {
        const { done, value } =
          await lecteur.read();

        if (done) {
          break;
        }

        tampon +=
          decodeur.decode(
            value,
            { stream: true }
          );

        const evenements =
          tampon.split('\n\n');

        tampon =
          evenements.pop() || '';

        for (
          const evenementBrut
          of evenements
        ) {
          traiterEvenementSSE(
            evenementBrut
          );
        }
      }

      if (tampon.trim()) {
        traiterEvenementSSE(
          tampon.trim()
        );
      }

      curseurFlux.remove();

      rendreReponseAssistant(
        corpsFlux,
        texteAccumule ||
          erreurRecue ||
          "Je n’ai pas pu générer de réponse."
      );

      if (
        erreurRecue &&
        texteAccumule
      ) {
        const noteErreur =
          document.createElement('p');

        noteErreur.style.cssText =
          'font-size:0.82rem;color:var(--ec-ink-soft,#64748B);font-style:italic;margin-top:0.4rem;';

        noteErreur.textContent =
          erreurRecue;

        corpsFlux.appendChild(
          noteErreur
        );
      }

    } catch (erreur) {
      if (erreur && erreur.name === 'AbortError') {
        // Interruption volontaire par l'utilisateur : on garde ce qui a
        // déjà été reçu, ce n'est pas une erreur à afficher comme telle.
        if (curseurFlux) {
          curseurFlux.remove();
        }

        if (corpsFlux) {
          rendreReponseAssistant(
            corpsFlux,
            texteAccumule || 'Génération interrompue.'
          );
        } else {
          retirerLigneAttente(ligneAttente);
          ajouterMessageAssistant(
            'Génération interrompue.',
            false
          );
        }
      } else {
        console.error(
          'Erreur assistant :',
          erreur
        );

        retirerLigneAttente(
          ligneAttente
        );

        ajouterMessageAssistant(
          erreur.message ||
          "Je n’arrive pas à répondre pour l’instant. Réessaie dans un instant.",
          false
        );
      }

    } finally {
      etat.enAttente = false;
      controleurAbandon = null;

      basculerBoutonEnvoyer('envoyer');
    }
  }

  function synchroniserEtatEnvoi() {
    if (!btnEnvoyer) {
      return;
    }

    if (!input) {
      btnEnvoyer.disabled =
        etat.enAttente;

      return;
    }

    btnEnvoyer.disabled =
      !input.value.trim() ||
      etat.enAttente;
  }

  function redimensionnerTextarea() {
    if (!input) return;

    input.style.height = 'auto';
    input.style.height =
      Math.min(input.scrollHeight, 160) + 'px';
  }

  if (input) {
    input.addEventListener(
      'input',
      () => {
        synchroniserEtatEnvoi();
        redimensionnerTextarea();
      }
    );

    input.addEventListener(
      'keydown',
      (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();

          if (form) {
            if (form.requestSubmit) {
              form.requestSubmit();
            } else {
              form.dispatchEvent(
                new Event('submit', {
                  cancelable: true,
                  bubbles: true
                })
              );
            }
          }
        }
      }
    );
  }

  if (btnEnvoyer) {
    // Clic sur le bouton pendant la génération = interruption, pas envoi.
    // On coupe ici avant que le submit du formulaire ne se déclenche.
    btnEnvoyer.addEventListener(
      'click',
      (e) => {
        if (etat.enAttente) {
          e.preventDefault();
          interrompreGeneration();
        }
      }
    );
  }

  if (form && input) {
    form.addEventListener(
      'submit',
      (e) => {
        e.preventDefault();

        const texte =
          input.value.trim();

        if (
          !texte ||
          etat.enAttente
        ) {
          return;
        }

        input.value = '';
        redimensionnerTextarea();

        fermerPanneauGenerer();

        synchroniserEtatEnvoi();

        envoyerMessage(texte);
      }
    );
  }

  function fermerPanneauGenerer() {
    const existant =
      document.getElementById(
        'panneau-generer'
      );

    if (existant) {
      existant.remove();
    }

    etat.panneauOuvert = false;
  }

  function fermerPanneauAjouter() {
    if (!panneauAjouter) {
      return;
    }

    panneauAjouter.hidden = true;

    if (btnAjouter) {
      btnAjouter.setAttribute(
        'aria-expanded',
        'false'
      );
    }
  }

  function basculerPanneauAjouter() {
    if (!panneauAjouter) {
      return;
    }

    const ouvert =
      panneauAjouter.hidden;

    panneauAjouter.hidden =
      !ouvert;

    if (btnAjouter) {
      btnAjouter.setAttribute(
        'aria-expanded',
        String(ouvert)
      );
    }
  }

  if (btnAjouter) {
    btnAjouter.addEventListener(
      'click',
      (e) => {
        e.stopPropagation();
        basculerPanneauAjouter();
      }
    );
  }

  if (btnAjouterEpreuve) {
    btnAjouterEpreuve.addEventListener(
      'click',
      () => {
        fermerPanneauAjouter();
        fermerSidebar();
        ouvrirPanneauVide();

        if (
          !MODE_DEMO &&
          ELEVE.niveau
        ) {
          afficherChoixMatiere(
            ELEVE.niveau,
            ELEVE.serie || null
          );
        } else {
          afficherChoixNiveau();
        }
      }
    );
  }

  if (btnHeaderMenu) {
    btnHeaderMenu.addEventListener(
      'click',
      () => {
        if (!sidebar) return;

        if (
          sidebar.classList.contains(
            'ouverte'
          )
        ) {
          fermerSidebar();
        } else {
          ouvrirSidebar();
        }
      }
    );
  }

  function ouvrirPanneauVide() {
    if (!saisie) {
      return null;
    }

    fermerPanneauGenerer();

    const panneau =
      document.createElement('div');

    panneau.className =
      'panneau-generer';

    panneau.id =
      'panneau-generer';

    saisie.appendChild(
      panneau
    );

    etat.panneauOuvert = true;

    return panneau;
  }

  function afficherChoixSequence() {
    const panneau =
      document.getElementById(
        'panneau-generer'
      );

    if (!panneau) return;

    panneau.innerHTML = '';

    const texte =
      document.createElement('p');

    texte.textContent =
      'Pour quelle séquence ?';

    panneau.appendChild(
      texte
    );

    const options =
      document.createElement('div');

    options.className =
      'panneau-generer-options';

    const ordinaux = {
      1: '1re',
      2: '2e',
      3: '3e',
      4: '4e',
      5: '5e',
      6: '6e'
    };

    [1, 2, 3, 4, 5, 6]
      .forEach((n) => {
        const btn =
          document.createElement(
            'button'
          );

        btn.type = 'button';
        btn.className =
          'chip-option';

        btn.textContent =
          `${ordinaux[n]} séquence`;

        btn.addEventListener(
          'click',
          () => {
            fermerPanneauGenerer();

            lancerGeneration(
              {
                type_document:
                  'Sequence',
                sequence: n
              },
              `Génère-moi une épreuve de la ${ordinaux[n]} séquence`
            );
          }
        );

        options.appendChild(
          btn
        );
      });

    panneau.appendChild(
      options
    );
  }

  async function afficherChoixAnneeExerciceOfficiel() {
    const panneau =
      document.getElementById(
        'panneau-generer'
      );

    if (!panneau) return;

    panneau.innerHTML =
      '<p>Chargement...</p>';

    const matiereCible =
      etat.matiere || 'Mathematiques';

    try {
      const params =
        new URLSearchParams({
          niveau: ELEVE.niveau,
          matiere: matiereCible
        });

      if (ELEVE.serie) {
        params.set(
          'serie',
          ELEVE.serie
        );
      }

      const reponse =
        await fetch(
          `${window.APP_URLS.chatAnnees}?${params}`,
          {
            headers: {
              'Accept':
                'application/json'
            }
          }
        );

      if (!reponse.ok) {
        throw new Error(
          'Impossible de charger les années.'
        );
      }

      const donnees =
        await reponse.json();

      const annees =
        Array.isArray(donnees.annees)
          ? donnees.annees
          : [];

      panneau.innerHTML = '';

      const texte =
        document.createElement('p');

      texte.textContent =
        annees.length
          ? `Exercice officiel de ${matiereCible} -- quelle année ?`
          : 'Aucune année indexée pour l’instant pour ta série/matière. Essaie une autre matière.';

      panneau.appendChild(
        texte
      );

      const options =
        document.createElement('div');

      options.className =
        'panneau-generer-options';

      annees.forEach(
        (annee) => {
          const btn =
            document.createElement(
              'button'
            );

          btn.type = 'button';
          btn.className =
            'chip-option';

          btn.textContent =
            String(annee);

          btn.addEventListener(
            'click',
            () =>
              afficherChoixNumeroExerciceOfficiel(
                annee,
                matiereCible
              )
          );

          options.appendChild(
            btn
          );
        }
      );

      panneau.appendChild(
        options
      );

    } catch (erreur) {
      console.error(
        'Erreur années (exercice officiel) :',
        erreur
      );

      panneau.innerHTML =
        '<p>Impossible de charger les années. Réessaie dans un instant.</p>';
    }
  }

  function afficherChoixNumeroExerciceOfficiel(
    annee,
    matiereCible
  ) {
    const panneau =
      document.getElementById(
        'panneau-generer'
      );

    if (!panneau) return;

    panneau.innerHTML = '';

    const libelleSerie =
      ELEVE.serie
        ? ` ${ELEVE.serie}`
        : '';

    const texte =
      document.createElement('p');

    texte.textContent =
      `${ELEVE.niveau}${libelleSerie} ${annee} -- quel exercice ?`;

    panneau.appendChild(
      texte
    );

    const options =
      document.createElement('div');

    options.className =
      'panneau-generer-options';

    const envoyerDemande = (
      question
    ) => {
      fermerPanneauGenerer();
      masquerAccueil();
      envoyerMessage(question);
    };

    [1, 2, 3, 4, 5, 6]
      .forEach((n) => {
        const btn =
          document.createElement(
            'button'
          );

        btn.type = 'button';
        btn.className =
          'chip-option';

        btn.textContent =
          `Exercice ${n}`;

        btn.addEventListener(
          'click',
          () =>
            envoyerDemande(
              `Donne-moi l’exercice ${n} du ${ELEVE.niveau}${libelleSerie} ${annee} en ${matiereCible}.`
            )
        );

        options.appendChild(
          btn
        );
      });

    panneau.appendChild(
      options
    );

    const btnInconnu =
      document.createElement(
        'button'
      );

    btnInconnu.type =
      'button';

    btnInconnu.className =
      'chip-option';

    btnInconnu.textContent =
      'Je ne connais pas le numéro';

    btnInconnu.addEventListener(
      'click',
      () =>
        envoyerDemande(
          `Propose-moi un exercice officiel du ${ELEVE.niveau}${libelleSerie} ${annee} en ${matiereCible}.`
        )
    );

    panneau.appendChild(
      document.createElement('br')
    );

    panneau.appendChild(
      btnInconnu
    );
  }

  async function afficherChoixNiveau() {
    const panneau =
      document.getElementById(
        'panneau-generer'
      );

    if (!panneau) return;

    panneau.innerHTML =
      '<p>Chargement...</p>';

    try {
      const reponse =
        await fetch(
          window.APP_URLS.chatNiveaux,
          {
            headers: {
              'Accept':
                'application/json'
            }
          }
        );

      if (!reponse.ok) {
        throw new Error(
          'Impossible de charger les niveaux.'
        );
      }

      const donnees =
        await reponse.json();

      const niveaux =
        Array.isArray(donnees.niveaux)
          ? donnees.niveaux
          : [];

      panneau.innerHTML = '';

      const texte =
        document.createElement('p');

      texte.textContent =
        'Quel niveau ?';

      panneau.appendChild(
        texte
      );

      const options =
        document.createElement('div');

      options.className =
        'panneau-generer-options';

      niveaux.forEach(
        (niveau) => {
          const btn =
            document.createElement(
              'button'
            );

          btn.type = 'button';
          btn.className =
            'chip-option';

          btn.textContent =
            niveau;

          btn.addEventListener(
            'click',
            () =>
              afficherChoixSerie(
                niveau
              )
          );

          options.appendChild(
            btn
          );
        }
      );

      panneau.appendChild(
        options
      );

    } catch (erreur) {
      console.error(
        'Erreur niveaux :',
        erreur
      );

      panneau.innerHTML =
        '<p>Impossible de charger les niveaux. Réessaie dans un instant.</p>';
    }
  }

  async function afficherChoixSerie(
    niveau
  ) {
    const panneau =
      document.getElementById(
        'panneau-generer'
      );

    if (!panneau) return;

    panneau.innerHTML =
      '<p>Chargement...</p>';

    try {
      const reponse =
        await fetch(
          `${window.APP_URLS.chatSeries}?niveau=${encodeURIComponent(niveau)}`,
          {
            headers: {
              'Accept':
                'application/json'
            }
          }
        );

      if (!reponse.ok) {
        throw new Error(
          'Impossible de charger les séries.'
        );
      }

      const donnees =
        await reponse.json();

      const series =
        Array.isArray(donnees.series)
          ? donnees.series
          : [];

      if (series.length === 0) {
        afficherChoixMatiere(
          niveau,
          null
        );
        return;
      }

      panneau.innerHTML = '';

      const texte =
        document.createElement('p');

      texte.textContent =
        'Quelle série ?';

      panneau.appendChild(
        texte
      );

      const options =
        document.createElement('div');

      options.className =
        'panneau-generer-options';

      series.forEach(
        (serie) => {
          const btn =
            document.createElement(
              'button'
            );

          btn.type = 'button';
          btn.className =
            'chip-option';

          btn.textContent =
            serie;

          btn.addEventListener(
            'click',
            () =>
              afficherChoixMatiere(
                niveau,
                serie
              )
          );

          options.appendChild(
            btn
          );
        }
      );

      panneau.appendChild(
        options
      );

    } catch (erreur) {
      console.error(
        'Erreur séries :',
        erreur
      );

      panneau.innerHTML =
        '<p>Impossible de charger les séries. Réessaie dans un instant.</p>';
    }
  }

  async function afficherChoixMatiere(
    niveau,
    serie
  ) {
    const panneau =
      document.getElementById(
        'panneau-generer'
      );

    if (!panneau) return;

    panneau.innerHTML =
      '<p>Chargement...</p>';

    try {
      const params =
        new URLSearchParams({
          niveau
        });

      if (serie) {
        params.set(
          'serie',
          serie
        );
      }

      const reponse =
        await fetch(
          `${window.APP_URLS.chatMatieres}?${params}`,
          {
            headers: {
              'Accept':
                'application/json'
            }
          }
        );

      if (!reponse.ok) {
        throw new Error(
          'Impossible de charger les matières.'
        );
      }

      const donnees =
        await reponse.json();

      const matieres =
        Array.isArray(donnees.matieres)
          ? donnees.matieres
          : [];

      panneau.innerHTML = '';

      const texte =
        document.createElement('p');

      texte.textContent =
        matieres.length
          ? 'Quelle matière ?'
          : 'Aucune matière indexée pour l’instant.';

      panneau.appendChild(
        texte
      );

      const options =
        document.createElement('div');

      options.className =
        'panneau-generer-options';

      matieres.forEach(
        (matiere) => {
          const btn =
            document.createElement(
              'button'
            );

          btn.type = 'button';
          btn.className =
            'chip-option';

          btn.textContent =
            matiere;

          btn.addEventListener(
            'click',
            () =>
              afficherChoixAnnee(
                niveau,
                serie,
                matiere
              )
          );

          options.appendChild(
            btn
          );
        }
      );

      panneau.appendChild(
        options
      );

      if (
        !MODE_DEMO &&
        ELEVE.niveau &&
        niveau === ELEVE.niveau
      ) {
        const btnAutre =
          document.createElement(
            'button'
          );

        btnAutre.type =
          'button';

        btnAutre.className =
          'chip-option';

        btnAutre.textContent =
          'Voir un autre niveau';

        btnAutre.addEventListener(
          'click',
          afficherChoixNiveau
        );

        panneau.appendChild(
          document.createElement(
            'br'
          )
        );

        panneau.appendChild(
          btnAutre
        );
      }

    } catch (erreur) {
      console.error(
        'Erreur matières :',
        erreur
      );

      panneau.innerHTML =
        '<p>Impossible de charger les matières. Réessaie dans un instant.</p>';
    }
  }

  async function afficherChoixAnnee(
    niveau,
    serie,
    matiere
  ) {
    const panneau =
      document.getElementById(
        'panneau-generer'
      );

    if (!panneau) return;

    panneau.innerHTML =
      '<p>Chargement...</p>';

    try {
      const params =
        new URLSearchParams({
          niveau,
          matiere
        });

      if (serie) {
        params.set(
          'serie',
          serie
        );
      }

      const reponse =
        await fetch(
          `${window.APP_URLS.chatAnnees}?${params}`,
          {
            headers: {
              'Accept':
                'application/json'
            }
          }
        );

      if (!reponse.ok) {
        throw new Error(
          'Impossible de charger les années.'
        );
      }

      const donnees =
        await reponse.json();

      const annees =
        Array.isArray(donnees.annees)
          ? donnees.annees
          : [];

      if (annees.length === 0) {
        lancerParcourir(
          niveau,
          serie,
          matiere,
          null
        );

        return;
      }

      panneau.innerHTML = '';

      const texte =
        document.createElement('p');

      texte.textContent =
        'Quelle année ?';

      panneau.appendChild(
        texte
      );

      const options =
        document.createElement('div');

      options.className =
        'panneau-generer-options';

      annees.forEach(
        (annee) => {
          const btn =
            document.createElement(
              'button'
            );

          btn.type = 'button';
          btn.className =
            'chip-option';

          btn.textContent =
            String(annee);

          btn.addEventListener(
            'click',
            () =>
              lancerParcourir(
                niveau,
                serie,
                matiere,
                annee
              )
          );

          options.appendChild(
            btn
          );
        }
      );

      const btnToutes =
        document.createElement(
          'button'
        );

      btnToutes.type =
        'button';

      btnToutes.className =
        'chip-option';

      btnToutes.textContent =
        'Toutes les années';

      btnToutes.addEventListener(
        'click',
        () =>
          lancerParcourir(
            niveau,
            serie,
            matiere,
            null
          )
      );

      options.appendChild(
        btnToutes
      );

      panneau.appendChild(
        options
      );

    } catch (erreur) {
      console.error(
        'Erreur années :',
        erreur
      );

      panneau.innerHTML =
        '<p>Impossible de charger les années. Réessaie dans un instant.</p>';
    }
  }

  async function lancerParcourir(
    niveau,
    serie,
    matiere,
    annee
  ) {
    fermerPanneauGenerer();
    masquerAccueil();

    const suffixeAnnee =
      annee
        ? ` ${annee}`
        : '';

    const libelleDemande =
      serie
        ? `Parcourir : ${niveau} ${serie} - ${matiere}${suffixeAnnee}`
        : `Parcourir : ${niveau} - ${matiere}${suffixeAnnee}`;

    ajouterMessageUtilisateur(
      libelleDemande
    );

    const ligneAttente =
      ajouterMessageAssistant(
        '',
        true
      );

    try {
      const params =
        new URLSearchParams({
          niveau,
          matiere
        });

      if (serie) {
        params.set(
          'serie',
          serie
        );
      }

      if (annee) {
        params.set(
          'annee',
          annee
        );
      }

      const reponseServeur =
        await fetch(
          `${window.APP_URLS.chatParcourir}?${params}`,
          {
            headers: {
              'Accept':
                'application/json'
            }
          }
        );

      if (!reponseServeur.ok) {
        throw new Error(
          'Impossible de récupérer les épreuves.'
        );
      }

      const donnees =
        await reponseServeur.json();

      const resultats =
        donnees.resultats;

      const erreur =
        donnees.erreur;

      retirerLigneAttente(
        ligneAttente
      );

      if (erreur) {
        throw new Error(
          erreur
        );
      }

      if (
        !Array.isArray(resultats) ||
        resultats.length === 0
      ) {
        ajouterMessageAssistant(
          'Je n’ai encore rien d’indexé pour cette combinaison. Essaie une autre matière ou série.',
          false
        );

        return;
      }

      ajouterCarteResultats(
        'Voici ce que j’ai trouvé :',
        resultats
      );

    } catch (erreur) {
      console.error(
        'Erreur parcours :',
        erreur
      );

      retirerLigneAttente(
        ligneAttente
      );

      ajouterMessageAssistant(
        erreur.message ||
        'Une erreur est survenue.',
        false
      );
    }
  }

  async function lancerGeneration(
    params,
    libelleUtilisateur
  ) {
    if (etat.enAttente) {
      return;
    }

    etat.enAttente = true;

    if (btnEnvoyer) {
      btnEnvoyer.disabled = true;
    }

    masquerAccueil();
    fermerPanneauGenerer();
    fermerPanneauAjouter();

    ajouterMessageUtilisateur(
      libelleUtilisateur
    );

    const ligneAttente =
      ajouterMessageAssistant(
        '',
        true
      );

    if (!ligneAttente) {
      etat.enAttente = false;
      synchroniserEtatEnvoi();
      return;
    }

    const corpsAttente =
      ligneAttente.querySelector(
        '.msg-bot-corps'
      );

    if (corpsAttente) {
      corpsAttente.innerHTML = `
        <div class="indicateur-reflexion">
          <div class="points-typing">
            <span></span>
            <span></span>
            <span></span>
          </div>
          <span class="texte-progression">
            Construction de l’énoncé...
          </span>
        </div>

        <div class="barre-progression"></div>
      `;
    }

    const etapesGeneration = [
      'Construction de l’énoncé...',
      'Mise en page des exercices...',
      'Vérification du barème...',
      'Finalisation du PDF...'
    ];

    let etapeIdx = 0;

    const spanEtape =
      corpsAttente
        ? corpsAttente.querySelector(
            '.texte-progression'
          )
        : null;

    ligneAttente._intervalReflexion =
      setInterval(() => {
        if (!spanEtape) {
          return;
        }

        etapeIdx =
          (etapeIdx + 1) %
          etapesGeneration.length;

        spanEtape.style.animation =
          'none';

        void spanEtape.offsetHeight;

        spanEtape.textContent =
          etapesGeneration[
            etapeIdx
          ];

        spanEtape.style.animation =
          'fondu 0.3s ease';

      }, 4000);

    try {
      const reponseServeur =
        await fetch(
          window.APP_URLS.generer,
          {
            method: 'POST',
            headers: {
              'Content-Type':
                'application/json',
              'Accept':
                'application/pdf, application/json'
            },
            body: JSON.stringify(
              params
            )
          }
        );

      const typeContenu =
        reponseServeur.headers
          .get('Content-Type') || '';

      if (
        !reponseServeur.ok ||
        typeContenu.includes(
          'application/json'
        )
      ) {
        let resultat = {};

        try {
          resultat =
            await reponseServeur.json();
        } catch {
          throw new Error(
            'Le serveur a renvoyé une réponse invalide.'
          );
        }

        throw new Error(
          resultat.erreur ||
          'La génération a échoué. Réessaie dans quelques minutes.'
        );
      }

      const dispo =
        reponseServeur.headers
          .get(
            'Content-Disposition'
          ) || '';

      const correspondance =
        dispo.match(
          /filename="?([^"]+)"?/
        );

      const nomFichier =
        correspondance
          ? correspondance[1]
          : 'epreuve.pdf';

      const blob =
        await reponseServeur.blob();

      if (!blob.size) {
        throw new Error(
          'Le PDF généré est vide.'
        );
      }

      const url =
        URL.createObjectURL(
          blob
        );

      const lien =
        document.createElement('a');

      lien.href = url;
      lien.download =
        nomFichier;

      document.body.appendChild(
        lien
      );

      lien.click();
      lien.remove();

      setTimeout(() => {
        URL.revokeObjectURL(
          url
        );
      }, 1000);

      retirerLigneAttente(
        ligneAttente
      );

      ajouterMessageAssistant(
        'Voilà ton épreuve. Elle vient d’être téléchargée. Bon courage pour la révision.',
        false
      );

    } catch (erreur) {
      console.error(
        'Erreur génération :',
        erreur
      );

      retirerLigneAttente(
        ligneAttente
      );

      ajouterMessageAssistant(
        erreur.message ||
        'La génération a échoué. Réessaie dans quelques minutes.',
        false
      );

    } finally {
      etat.enAttente = false;
      synchroniserEtatEnvoi();
    }
  }

  function mettreAJourAriaSidebar(
    ouvert
  ) {
    if (
      btnSidebarToggleMobile
    ) {
      btnSidebarToggleMobile.setAttribute(
        'aria-expanded',
        String(ouvert)
      );
    }
  }

  function ouvrirSidebar() {
    if (!sidebar) return;

    sidebar.classList.add(
      'ouverte'
    );

    if (backdrop) {
      backdrop.classList.add(
        'visible'
      );
    }

    mettreAJourAriaSidebar(
      true
    );
  }

  function fermerSidebar() {
    if (!sidebar) return;

    sidebar.classList.remove(
      'ouverte'
    );

    if (backdrop) {
      backdrop.classList.remove(
        'visible'
      );
    }

    mettreAJourAriaSidebar(
      false
    );
  }

  if (
    btnSidebarToggleMobile
  ) {
    btnSidebarToggleMobile.addEventListener(
      'click',
      () => {
        if (
          sidebar &&
          sidebar.classList.contains(
            'ouverte'
          )
        ) {
          fermerSidebar();
        } else {
          ouvrirSidebar();
        }
      }
    );
  }

  if (backdrop) {
    backdrop.addEventListener(
      'click',
      fermerSidebar
    );
  }

  if (btnNouvelleConversation) {
    btnNouvelleConversation.addEventListener(
      'click',
      async () => {
        fermerPanneauGenerer();
        fermerPanneauAjouter();
        fermerSidebar();

        if (
          !MODE_DEMO &&
          etat.matiere
        ) {
          try {
            await fetch(
              window.APP_URLS.nouvelleConversation,
              {
                method: 'POST',
                headers: {
                  'Content-Type':
                    'application/json',
                  'Accept':
                    'application/json'
                },
                body: JSON.stringify({
                  matiere:
                    etat.matiere
                })
              }
            );
          } catch (erreur) {
            console.warn(
              'Impossible de réinitialiser l’historique côté serveur.',
              erreur
            );
          }
        }

        if (fenetre) {
          fenetre.innerHTML = '';
        }

        afficherAccueil();

        if (input) {
          input.value = '';
          input.focus();
        }

        synchroniserEtatEnvoi();
      }
    );
  }

  if (btnSidebarExamen) {
    btnSidebarExamen.addEventListener(
      'click',
      () => {
        if (
          etat.enAttente ||
          btnSidebarExamen.disabled
        ) {
          return;
        }

        fermerPanneauGenerer();
        fermerPanneauAjouter();
        fermerSidebar();

        lancerGeneration(
          {
            type_document:
              'Examen',
            serie:
              SERIE_GENERATION_DISPONIBLE
          },
          'Génère-moi un Examen officiel (Bac blanc)'
        );
      }
    );
  }

  if (btnSidebarSequence) {
    btnSidebarSequence.addEventListener(
      'click',
      () => {
        if (
          etat.enAttente ||
          btnSidebarSequence.disabled
        ) {
          return;
        }

        fermerSidebar();
        ouvrirPanneauVide();
        afficherChoixSequence();
      }
    );
  }

  if (btnSidebarParcourir) {
    btnSidebarParcourir.addEventListener(
      'click',
      () => {
        fermerSidebar();
        ouvrirPanneauVide();

        if (
          !MODE_DEMO &&
          ELEVE.niveau
        ) {
          afficherChoixMatiere(
            ELEVE.niveau,
            ELEVE.serie || null
          );
        } else {
          afficherChoixNiveau();
        }
      }
    );
  }

  const conteneurMatieres =
    document.getElementById(
      'sidebar-matieres'
    );

  if (conteneurMatieres) {

    function marquerChipActive() {
      conteneurMatieres
        .querySelectorAll(
          '.chip-matiere'
        )
        .forEach((chip) => {
          chip.classList.toggle(
            'actif',
            chip.dataset.matiere ===
              etat.matiere
          );
        });
    }

    conteneurMatieres.addEventListener(
      'click',
      (e) => {
        const chip =
          e.target.closest(
            '.chip-matiere'
          );

        if (
          !chip ||
          chip.dataset.matiere ===
            etat.matiere ||
          etat.chargementHistorique ||
          etat.enAttente
        ) {
          return;
        }

        etat.matiere =
          chip.dataset.matiere;

        marquerChipActive();

        fermerPanneauGenerer();
        fermerSidebar();

        chargerEtAfficherHistorique();
      }
    );

    marquerChipActive();
  }

  document.addEventListener(
    'click',
    (e) => {
      const chemin =
        e.composedPath();

      if (
        etat.panneauOuvert &&
        saisie &&
        !chemin.includes(
          saisie
        ) &&
        sidebar &&
        !chemin.includes(
          sidebar
        )
      ) {
        fermerPanneauGenerer();
      }

      if (
        panneauAjouter &&
        !panneauAjouter.hidden &&
        saisie &&
        !chemin.includes(
          saisie
        )
      ) {
        fermerPanneauAjouter();
      }
    }
  );

  document.addEventListener(
    'keydown',
    (e) => {
      if (e.key !== 'Escape') {
        return;
      }

      fermerPanneauGenerer();
      fermerPanneauAjouter();
      fermerSidebar();
    }
  );

  // Défilement manuel de l'utilisateur (molette/tactile) = intention réelle
  // de lire ; on distingue ça de nos propres scrolls programmatiques pour
  // savoir quand arrêter de suivre automatiquement le flux.
  if (fenetre) {
    ['wheel', 'touchmove'].forEach((evt) => {
      fenetre.addEventListener(
        evt,
        () => {
          etat.suivreDefilement = estAncreEnBas();
        },
        { passive: true }
      );
    });
  }

  chargerEtAfficherHistorique();

  if (input) {
    input.focus();
  }

})();