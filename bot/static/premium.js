/* Blokady premium w panelu web.
 *
 * Sposób użycia w dowolnej stronie HTML — nic poza atrybutem:
 *
 *   <div class="card" data-premium="alloc.risk"> ...prawdziwa zawartość... </div>
 *
 * Skrypt sam sprawdzi, czy użytkownik ma premium. Jeśli nie — owinie zawartość,
 * rozmyje ją, dołoży żółtą obwódkę z kłódką i przekieruje kliknięcie na
 * /premium?f=alloc.risk. Jeśli ma — nie robi nic, karta działa normalnie.
 *
 * Wymaga wcześniejszego wczytania auth.js i premium.css.
 */
(function () {
  let cache = null;

  async function catalog() {
    if (cache) return cache;
    const auth = window.Portfel && window.Portfel.auth;
    const get = auth ? auth.fetch.bind(auth) : fetch;
    try {
      const r = await get("/api/premium/features");
      cache = await r.json();
    } catch {
      // Brak odpowiedzi serwera nie może zablokować panelu — wtedy nie blokujemy nic.
      cache = { premium: true, features: [] };
    }
    return cache;
  }

  function feature(id) {
    return ((cache && cache.features) || []).find((f) => f.id === id) || null;
  }

  /** Ślad w analityce — wiemy, które kłódki ludzie naprawdę klikają. */
  function track(event, id) {
    const auth = window.Portfel && window.Portfel.auth;
    const send = auth ? auth.fetch.bind(auth) : fetch;
    try {
      send("/api/premium/event", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event, feature: id, platform: "web" }),
        keepalive: true,
      });
    } catch {}
  }

  function open(id) {
    track("lock_click", id);
    location.href = "/premium?f=" + encodeURIComponent(id);
  }

  /** Zamienia element w zablokowaną kartę. Idempotentne. */
  function lock(el, id) {
    if (!el || el.dataset.premiumLocked === "1") return;
    const f = feature(id) || { title: "Funkcja premium", tagline: "" };

    const under = document.createElement("div");
    under.className = "premium-under";
    while (el.firstChild) under.appendChild(el.firstChild);

    const veil = document.createElement("div");
    veil.className = "premium-veil";
    veil.innerHTML =
      '<div class="padlock">🔒</div>' +
      '<div class="title"></div>' +
      '<div class="desc"></div>' +
      '<button class="cta" type="button">Zobacz, co to daje</button>';
    veil.querySelector(".title").textContent = f.title;
    veil.querySelector(".desc").textContent = f.tagline || "";

    el.appendChild(under);
    el.appendChild(veil);
    el.classList.add("premium-locked");
    el.dataset.premiumLocked = "1";
    el.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); open(id); });
    track("lock_seen", id);
  }

  /** Mała kłódka przy tytule — gdy zasłanianie całej karty psułoby układ. */
  function badge(id, label) {
    const b = document.createElement("span");
    b.className = "premium-badge";
    b.textContent = "🔒 " + (label || "PREMIUM");
    b.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); open(id); });
    return b;
  }

  async function scan(root) {
    const c = await catalog();
    (root || document).querySelectorAll("[data-premium]").forEach((el) => {
      const id = el.getAttribute("data-premium");
      const f = feature(id);
      if (c.premium || !f || f.status !== "live") {
        el.classList.add("premium-on");
        return;
      }
      lock(el, id);
    });
  }

  window.Portfel = window.Portfel || {};
  window.Portfel.premium = {
    catalog, feature, lock, badge, scan, open, track,
    get active() { return !!(cache && cache.premium); },
    /** Po zakupie: wyczyść cache i przeładuj widok. */
    reset() { cache = null; },
  };

  document.addEventListener("DOMContentLoaded", () => {
    const auth = window.Portfel && window.Portfel.auth;
    (auth ? auth.ready() : Promise.resolve()).then(() => scan());
  });
})();
