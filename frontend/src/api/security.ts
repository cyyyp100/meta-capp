// security.ts — Nonce de lancement (S1). La coque desktop ouvre la fenêtre sur
// /?lt=<nonce> ; on le pose en cookie SameSite=Strict (couvre fetch, <img> et
// WebSocket, et un site tiers ne peut pas l'envoyer), puis on nettoie l'URL.
// En dev (Vite, pas de coque) il n'y a pas de nonce : tout reste inerte.

const COOKIE = "nwol_lt";
let token: string | null = null;

export function initLaunchToken(): void {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("lt");
  if (fromUrl) {
    token = fromUrl;
    sessionStorage.setItem(COOKIE, fromUrl);
    document.cookie = `${COOKIE}=${fromUrl}; path=/; SameSite=Strict`;
    params.delete("lt");
    const qs = params.toString();
    window.history.replaceState(null, "", window.location.pathname + (qs ? `?${qs}` : ""));
    return;
  }
  token = sessionStorage.getItem(COOKIE);
  if (token) {
    document.cookie = `${COOKIE}=${token}; path=/; SameSite=Strict`;
  }
}

// Suffixe query pour les URLs WebSocket (filet si le moteur web n'envoie pas
// les cookies sur le handshake WS).
export function wsTokenSuffix(): string {
  return token ? `?lt=${encodeURIComponent(token)}` : "";
}

// Paramètre additionnel pour les URLs qui ont déjà une query (ex. <img> des
// pages PDF : impossible d'y joindre un header).
export function extraTokenParam(): string {
  return token ? `&lt=${encodeURIComponent(token)}` : "";
}
