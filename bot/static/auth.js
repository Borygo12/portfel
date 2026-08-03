/* Logowanie w panelu web — wspólne dla wszystkich stron HTML.
 *
 * Rozmawiamy wprost z GoTrue (API uwierzytelniania Supabase) przez `fetch`, bez
 * biblioteki klienckiej: panel to zwykłe pliki HTML bez bundlera, więc jedna
 * paczka mniej to jedna rzecz mniej, która może się rozjechać z wersją.
 *
 * Sesja leży w localStorage. Token dostępowy żyje godzinę i odświeżamy go sami,
 * z zapasem, przy każdym pobraniu.
 *
 * Użycie:
 *   await Portfel.auth.ready();          // wczytuje konfigurację i sesję
 *   Portfel.auth.user                    // null albo {id, email, name, avatar}
 *   await Portfel.auth.fetch("/api/me")  // fetch z dołączonym tokenem
 */
(function () {
  const KEY = "portfel.session";
  const state = { cfg: null, session: null, user: null, listeners: [] };

  const load = () => {
    try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch { return null; }
  };
  const save = (s) => {
    state.session = s;
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  };

  async function config() {
    if (state.cfg) return state.cfg;
    const r = await fetch("/api/auth/config", { headers: apiHeaders() });
    state.cfg = await r.json();
    return state.cfg;
  }

  /* Token panelu (ten z api_token.txt) jedzie w nagłówku, gdy wchodzisz z LAN —
     inaczej serwer odrzuciłby żądanie, zanim w ogóle dojdzie do konta. */
  function apiHeaders() {
    const t = new URLSearchParams(location.search).get("token")
           || localStorage.getItem("portfel.apiToken") || "";
    if (t) localStorage.setItem("portfel.apiToken", t);
    return t ? { "X-API-Token": t } : {};
  }

  async function gotrue(path, body, token) {
    const cfg = await config();
    if (!cfg.configured) throw new Error("Logowanie nie jest skonfigurowane — patrz keys/README.md");
    const r = await fetch(cfg.url + "/auth/v1" + path, {
      method: "POST",
      headers: {
        apikey: cfg.anon_key,
        "Content-Type": "application/json",
        ...(token ? { Authorization: "Bearer " + token } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const js = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(js.error_description || js.msg || js.error || "Nie udało się zalogować");
    return js;
  }

  function adopt(js) {
    if (!js || !js.access_token) return null;
    save({
      access_token: js.access_token,
      refresh_token: js.refresh_token,
      // zapisujemy moment wygaśnięcia, nie długość życia — po przeładowaniu strony
      // „3600 sekund" nie znaczy już nic
      expires_at: Math.floor(Date.now() / 1000) + (js.expires_in || 3600),
    });
    state.user = fromUser(js.user);
    emit();
    return state.user;
  }

  const fromUser = (u) => u ? {
    id: u.id,
    email: u.email || "",
    name: (u.user_metadata || {}).full_name || (u.user_metadata || {}).name || "",
    avatar: (u.user_metadata || {}).avatar_url || "",
  } : null;

  function emit() { state.listeners.forEach((fn) => { try { fn(state.user); } catch {} }); }

  async function refresh() {
    const s = state.session;
    if (!s || !s.refresh_token) return null;
    try {
      return adopt(await gotrue("/token?grant_type=refresh_token",
                                { refresh_token: s.refresh_token }));
    } catch {
      save(null); state.user = null; emit();
      return null;
    }
  }

  async function token() {
    const s = state.session;
    if (!s) return "";
    // 60 sekund zapasu: token, który wygasa w trakcie lotu żądania, jest bezużyteczny
    if (s.expires_at && s.expires_at - 60 < Math.floor(Date.now() / 1000)) {
      await refresh();
    }
    return state.session ? state.session.access_token : "";
  }

  /** Odczytanie tokenów, którymi Google odesłał nas z powrotem (fragment adresu). */
  async function consumeCallback() {
    const hash = location.hash.startsWith("#") ? location.hash.slice(1) : "";
    if (!hash) return false;
    const p = new URLSearchParams(hash);
    const at = p.get("access_token");
    if (!at) return false;
    save({
      access_token: at,
      refresh_token: p.get("refresh_token") || "",
      expires_at: Math.floor(Date.now() / 1000) + parseInt(p.get("expires_in") || "3600", 10),
    });
    history.replaceState(null, "", location.pathname + location.search);
    await me();
    return true;
  }

  async function me() {
    const t = await token();
    if (!t) { state.user = null; emit(); return null; }
    const cfg = await config();
    const r = await fetch(cfg.url + "/auth/v1/user",
                          { headers: { apikey: cfg.anon_key, Authorization: "Bearer " + t } });
    if (!r.ok) { save(null); state.user = null; emit(); return null; }
    state.user = fromUser(await r.json());
    emit();
    return state.user;
  }

  let readyPromise = null;
  function ready() {
    if (!readyPromise) {
      readyPromise = (async () => {
        await config();
        state.session = load();
        if (!(await consumeCallback()) && state.session) await me();
        return state.user;
      })();
    }
    return readyPromise;
  }

  const api = {
    ready,
    get user() { return state.user; },
    get configured() { return !!(state.cfg && state.cfg.configured); },
    onChange(fn) { state.listeners.push(fn); return () => {
      state.listeners = state.listeners.filter((f) => f !== fn);
    }; },

    async signIn(email, password) {
      return adopt(await gotrue("/token?grant_type=password", { email, password }));
    },

    async signUp(email, password) {
      const js = await gotrue("/signup", { email, password });
      // gdy w Supabase włączone jest potwierdzanie adresu, nie ma jeszcze tokenu
      return js.access_token ? adopt(js) : null;
    },

    /** Link jednorazowy na e-mail — dla tych, którzy nie chcą wymyślać hasła. */
    async magicLink(email) {
      await gotrue("/otp?redirect_to=" + encodeURIComponent(redirectUrl()),
                   { email, create_user: true });
      return true;
    },

    signInGoogle() {
      return config().then((cfg) => {
        if (!cfg.configured) throw new Error("Logowanie nie jest skonfigurowane");
        location.href = cfg.url + "/auth/v1/authorize?provider=google&redirect_to="
                      + encodeURIComponent(redirectUrl());
      });
    },

    async signOut() {
      const t = await token();
      if (t) { try { await gotrue("/logout", {}, t); } catch {} }
      save(null); state.user = null; emit();
    },

    /** fetch do naszego serwera z dołączonym kontem i tokenem panelu. */
    async fetch(url, opts = {}) {
      const t = await token();
      return fetch(url, {
        ...opts,
        headers: {
          ...(opts.headers || {}),
          ...apiHeaders(),
          ...(t ? { Authorization: "Bearer " + t } : {}),
        },
      });
    },

    apiHeaders,
    token,
  };

  function redirectUrl() {
    // wracamy zawsze na stronę konta — ona umie odebrać tokeny z adresu
    return location.origin + "/account";
  }

  window.Portfel = window.Portfel || {};
  window.Portfel.auth = api;
})();
