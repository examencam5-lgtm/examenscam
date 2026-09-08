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

const CACHE_NAME = "examenscam-static-v1";

// Seuls des chemins STATIQUES connus et stables -- jamais de route
// dynamique ici. Si tu ajoutes un nouveau fichier CSS/JS stable,
// ajoute-le à cette liste.
const FICHIERS_A_METTRE_EN_CACHE = [
  "/static/css/nouvelles_pages.css",
  "/static/img/logo.svg",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(FICHIERS_A_METTRE_EN_CACHE))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // Nettoie les anciens caches si CACHE_NAME change un jour (nouvelle
  // version du service worker) -- évite une accumulation silencieuse.
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

  // Ne jamais intercepter une requête qui n'est pas un GET simple
  // (POST du chat, formulaires de connexion/paiement) -- uniquement
  // du cache-first pour les fichiers statiques listés ci-dessus.
  if (event.request.method !== "GET") return;
  if (!url.pathname.startsWith("/static/")) return;

  event.respondWith(
    caches.match(event.request).then((reponse_cache) => {
      if (reponse_cache) return reponse_cache;
      return fetch(event.request).then((reponse_reseau) => {
        // Met en cache à la volée tout autre fichier /static/ rencontré
        // (ex: une image d'une épreuve), sans devoir tout lister à
        // l'avance dans FICHIERS_A_METTRE_EN_CACHE.
        const clone = reponse_reseau.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return reponse_reseau;
      });
    })
  );
});