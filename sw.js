// sw.js — ExamensCam
// Service worker volontairement MINIMAL : le but ici n'est pas un vrai
// mode hors-ligne (le chat élève a besoin du réseau pour parler à
// Gemini/Hugging Face, impossible à faire fonctionner offline), mais
// juste d'accélérer les visites répétées en mettant en cache les
// fichiers STATIQUES (CSS, JS, logo, icônes) -- exactement ce qui ne
// change jamais d'une visite à l'autre.
//
// PRINCIPE DE SÉCURITÉ IMPORTANT : ce service worker ne touche JAMAIS
// aux routes dynamiques (/, /assistant-eleve/*, /connexion, /mon-compte,
// /abonnement/*) -- les mettre en cache risquerait de montrer une page
// périmée (mauvais solde de crédits, ancien historique de chat) ou,
// pire, d'interférer avec le flux de paiement redirigé vers Monetbil.
//
// STRATEGIE DE CACHE (important, lu ça avant de toucher au fichier) :
// - JS et CSS changent a chaque session de travail -> reseau-d'abord
//   (network-first). Le fichier en cache ne sert que si le reseau est
//   injoignable (ex: coupure a Maroua) -- jamais en priorite.
// - Logo, icones, images d'epreuves : ne changent (quasi) jamais ->
//   cache-first, comme avant, pour la vitesse.
//
// A CHAQUE DEPLOIEMENT MODIFIANT JS/CSS : augmente CACHE_VERSION
// ci-dessous (v1 -> v2 -> v3...). Ca force tous les telephones a
// jeter leur ancien cache au prochain chargement, meme ceux qui ne
// repasseront jamais par un hard-refresh. C'est la seule vraie
// protection contre le bug qu'on vient de debugger.

const CACHE_VERSION = "v4";
const CACHE_NAME = `examenscam-static-${CACHE_VERSION}`;

// Fichiers a forte volatilite -- toujours verifies au reseau d'abord.
const FICHIERS_RESEAU_DABORD = [
  "/static/css/nouvelles_pages.css",
  "/static/css/assistant_eleve.css",
  "/static/js/assistant_eleve.js",
];

// Fichiers quasi figes -- cache-first, comme avant.
const FICHIERS_CACHE_DABORD = [
  "/static/img/logo.svg",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      cache.addAll([...FICHIERS_RESEAU_DABORD, ...FICHIERS_CACHE_DABORD])
    )
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // Nettoie tous les anciens caches (v1, v2...) des qu'une nouvelle
  // CACHE_VERSION est activee -- evite une accumulation silencieuse
  // et surtout evite de continuer a lire un cache perime.
  event.waitUntil(
    caches.keys().then((noms) =>
      Promise.all(
        noms
          .filter((nom) => nom !== CACHE_NAME)
          .map((nom) => caches.delete(nom))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Ne jamais intercepter une requete qui n'est pas un GET simple
  // (POST du chat, formulaires de connexion/paiement) -- uniquement
  // du cache pour les fichiers statiques listes ci-dessus.
  if (event.request.method !== "GET") return;
  if (!url.pathname.startsWith("/static/")) return;

  const estVolatile = FICHIERS_RESEAU_DABORD.some(
    (chemin) => url.pathname === chemin
  );

  if (estVolatile) {
    // Reseau d'abord : on essaie toujours d'avoir la derniere version.
    // Le cache ne sert que si le reseau est injoignable (offline reel,
    // ou coupure temporaire dans une zone a faible couverture).
    event.respondWith(
      fetch(event.request)
        .then((reponse_reseau) => {
          const clone = reponse_reseau.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return reponse_reseau;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Cache d'abord pour tout le reste (logo, icones, images d'epreuves,
  // et tout autre fichier /static/ rencontre en cours de route).
  event.respondWith(
    caches.match(event.request).then((reponse_cache) => {
      if (reponse_cache) return reponse_cache;
      return fetch(event.request).then((reponse_reseau) => {
        const clone = reponse_reseau.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return reponse_reseau;
      });
    })
  );
});