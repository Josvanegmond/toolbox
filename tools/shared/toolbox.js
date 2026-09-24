/* Shared toolbox behaviour: light/dark theme toggle and NL/EN language switch.
 *
 * Markup it works with:
 *   <button class="themebtn" id="themeToggle">…</button>
 *   <div class="langtoggle"><button data-lang-btn="nl">NL</button><button data-lang-btn="en">EN</button></div>
 *   elements with data-i18n (text), data-i18n-html (markup), data-i18n-placeholder, data-i18n-aria (aria-label)
 *
 * Choices are stored in localStorage (shared by all tools on this site) when the browser allows it.
 */
window.Toolbox = (() => {
  "use strict";
  const store = {
    get(k){ try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v){ try { localStorage.setItem(k, v); } catch (e) {} },
  };

  // fallback: "system" follows the OS setting until the viewer picks one; "light"/"dark" force a default
  function initTheme({ button, fallback = "system", onChange } = {}){
    const root = document.documentElement, mql = window.matchMedia("(prefers-color-scheme: dark)");
    let explicit = store.get("toolbox.theme") || (fallback === "system" ? null : fallback);
    const effective = () => explicit || (mql.matches ? "dark" : "light");
    function apply(){
      if (explicit) root.setAttribute("data-theme", explicit); else root.removeAttribute("data-theme");
      if (button) {
        const dark = effective() === "dark";
        button.innerHTML = dark ? "&#9789;" : "&#9788;";
        button.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
      }
      if (onChange) onChange(effective());
    }
    if (button) button.addEventListener("click", () => {
      explicit = effective() === "dark" ? "light" : "dark";
      store.set("toolbox.theme", explicit);
      apply();
    });
    mql.addEventListener?.("change", () => { if (!explicit) apply(); });
    apply();
    return { effective };
  }

  // dict = { nl: {key: text}, en: {...} }; t(key) falls back to the default language, then to the key
  function initLang({ dict, fallback = "nl", onChange } = {}){
    let lang = store.get("toolbox.lang");
    if (!dict[lang]) lang = fallback;
    const lookup = (key) => (dict[lang] && dict[lang][key] !== undefined ? dict[lang][key] : dict[fallback][key]);
    const t = (key) => { const v = lookup(key); return v === undefined ? key : v; };
    // elements whose key is missing from both languages keep their current text
    const each = (attr, fn) => document.querySelectorAll("[" + attr + "]").forEach(el => {
      const v = lookup(el.getAttribute(attr));
      if (v !== undefined) fn(el, v);
    });
    function apply(next){
      lang = dict[next] ? next : fallback;
      store.set("toolbox.lang", lang);
      document.documentElement.lang = lang;
      each("data-i18n", (el, v) => { el.textContent = v; });
      each("data-i18n-html", (el, v) => { el.innerHTML = v; });
      each("data-i18n-placeholder", (el, v) => { el.setAttribute("placeholder", v); });
      each("data-i18n-aria", (el, v) => { el.setAttribute("aria-label", v); });
      document.querySelectorAll("[data-lang-btn]").forEach(b => { b.setAttribute("aria-pressed", String(b.getAttribute("data-lang-btn") === lang)); });
      if (onChange) onChange(lang);
    }
    document.querySelectorAll("[data-lang-btn]").forEach(b => b.addEventListener("click", () => apply(b.getAttribute("data-lang-btn"))));
    apply(lang);
    return { t, get lang(){ return lang; }, set: apply };
  }

  return { initTheme, initLang, store };
})();
