// Nonce de lancement (S1) côté client : capture depuis l'URL, cookie posé,
// URL nettoyée, suffixes de query corrects.
import { beforeEach, describe, expect, it } from "vitest";

import { extraTokenParam, initLaunchToken, wsTokenSuffix } from "./security";

describe("initLaunchToken", () => {
  beforeEach(() => {
    sessionStorage.clear();
    document.cookie = "nwol_lt=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
    window.history.replaceState(null, "", "/");
  });

  it("capture ?lt=, pose le cookie et nettoie l'URL", () => {
    window.history.replaceState(null, "", "/?lt=jeton-test&autre=1");
    initLaunchToken();
    expect(document.cookie).toContain("nwol_lt=jeton-test");
    expect(window.location.search).not.toContain("lt=jeton-test");
    expect(window.location.search).toContain("autre=1");
    expect(wsTokenSuffix()).toBe("?lt=jeton-test");
    expect(extraTokenParam()).toBe("&lt=jeton-test");
  });

  it("retombe sur sessionStorage après rechargement (URL déjà nettoyée)", () => {
    sessionStorage.setItem("nwol_lt", "jeton-persiste");
    initLaunchToken();
    expect(wsTokenSuffix()).toBe("?lt=jeton-persiste");
  });

  it("reste inerte sans nonce (dev)", () => {
    initLaunchToken();
    expect(wsTokenSuffix()).toBe("");
    expect(extraTokenParam()).toBe("");
  });
});
