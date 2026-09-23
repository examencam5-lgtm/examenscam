// sw.js — ExamensCam
// Service worker volontairement MINIMAL : le but ici n'est pas un vrai
// mode hors-ligne (le chat élève a besoin du réseau pour parler à
// Gemini/Hugging Face, impossible à faire fonctionner offline), mais
// juste d'accélérer les visites répétées en mettant en cache les
// fichiers STATIQUES (CSS, JS, logo, icônes) -- exactement ce qui ne
// change jamais d'une visite à l'autre.
//
// PRINCIPE DE SECURITE IMPORTANT : ce service worker ne touche JAMAIS
// aux routes dynamiques (/, /assistant-eleve/*, /connexion, /mon-compte,
// /abonnement/*) -- les mettre en cache risquerait de montrer une page
// perimee (mauvais solde de credits, ancien historique de chat) ou,
// pire, d'interferer avec le flux de paiement redirige vers Monetbil.
//
// STRATEGIE DE CACHE :
// - JS et CSS changent a chaque session de travail -> reseau-d'abord
//   (network-first). Le fichier en cache ne sert que si le reseau est
//   injoignable (coupure a Maroua).
// - Logo, icones, images d'epreuves : ne changent (quasi) jamais ->
//   cache-first, pour la vitesse.
//
// A CHAQUE DEPLOIEMENT MODIFIANT JS/CSS : augmente CACHE_VERSION
// ci-dessous. Ca force tous les telephones a jeter leur ancien cache
// au prochain chargement.

const CACHE_VERSION = "v5";
const CACHE_NAME = `examenscam-static-${CACHE_VERSION}`;

const FICHIERS_RESEAU_DABORD = [
  "/static/css/nouvelles_pages.css",
  "/static/css/assistant_eleve.css",
  "/static/js/assistant_eleve.js",
];

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
  event.waitUntil(
    caches.keys().then((noms) =>
      Promise.all(
        noms.filter((nom) => nom !== CACHE_NAME).map((nom) => caches.delete(nom))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  if (event.request.method !== "GET") return;
  if (!url.pathname.startsWith("/static/")) return;

  const estVolatile = FICHIERS_RESEAU_DABORD.some(
    (chemin) => url.pathname === chemin
  );

  if (estVolatile) {
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