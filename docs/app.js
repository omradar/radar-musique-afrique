"use strict";

const I18N = {
  fr: {
    title: "Radar Musique Afrique",
    tagline: "Actus, business et industrie de la musique africaine. Mise à jour toutes les 6 heures.",
    tabs: { news: "Actus", newsletters: "Newsletters", sources: "Sources" },
    search: "Rechercher un titre, un artiste, une source...",
    allCategories: "Toutes les catégories",
    allLangs: "Toutes les langues",
    allKinds: "Tous les types de source",
    kinds: { primary: "Sources primaires", secondary: "Presse qui relaie" },
    langs: { fr: "Français", en: "English" },
    periods: { 7: "7 derniers jours", 30: "30 derniers jours", 90: "90 derniers jours" },
    hide: "Masquer les non confirmés",
    categories: { actus: "Actus", business: "Business", streaming: "Streaming", live: "Live et festivals", droits: "Droits d'auteur" },
    primary: "Source primaire",
    unconfirmed: "Non confirmé : source à recouper",
    confirmed: "Recoupé",
    via: "via",
    count: (n) => `${n} article${n > 1 ? "s" : ""}`,
    more: "Voir plus",
    updated: "Dernière mise à jour",
    never: "Pas encore de données : le premier passage du collecteur n'a pas eu lieu.",
    noNewsletters: "Aucune newsletter publiée pour le moment. La première sort un jeudi à 18h (Paris).",
    readNl: "Lire",
    srcIntro: "État de chaque source au dernier passage. Une source en erreur n'a pas de flux exploitable.",
    items: "articles",
    ok: "OK",
    ko: "Erreur",
    footer: "Titres, extraits courts et liens vers les sources d'origine. Les contenus appartiennent à leurs éditeurs.",
  },
  en: {
    title: "Africa Music Radar",
    tagline: "News, business and industry of African music. Updated every 6 hours.",
    tabs: { news: "News", newsletters: "Newsletters", sources: "Sources" },
    search: "Search a title, an artist, a source...",
    allCategories: "All categories",
    allLangs: "All languages",
    allKinds: "All source types",
    kinds: { primary: "Primary sources", secondary: "Press relaying" },
    langs: { fr: "Français", en: "English" },
    periods: { 7: "Last 7 days", 30: "Last 30 days", 90: "Last 90 days" },
    hide: "Hide unconfirmed",
    categories: { actus: "News", business: "Business", streaming: "Streaming", live: "Live and festivals", droits: "Rights" },
    primary: "Primary source",
    unconfirmed: "Unconfirmed: source to cross-check",
    confirmed: "Cross-checked",
    via: "via",
    count: (n) => `${n} article${n > 1 ? "s" : ""}`,
    more: "Show more",
    updated: "Last update",
    never: "No data yet: the collector has not run for the first time.",
    noNewsletters: "No newsletter published yet. The first one goes out on a Thursday at 6pm (Paris).",
    readNl: "Read",
    srcIntro: "Status of each source at the last run. A source in error has no usable feed.",
    items: "articles",
    ok: "OK",
    ko: "Error",
    footer: "Headlines, short excerpts and links to the original sources. Content belongs to its publishers.",
  },
};

const state = { lang: "fr", tab: "news", shown: 40, articles: [], updated: null, newsletters: [], health: [] };
const PAGE = 40;
const $ = (id) => document.getElementById(id);

function t() { return I18N[state.lang]; }

function el(tag, opts = {}, children = []) {
  const node = document.createElement(tag);
  if (opts.cls) node.className = opts.cls;
  if (opts.text !== undefined) node.textContent = opts.text;
  if (opts.href && /^https?:\/\//i.test(opts.href)) {
    node.href = opts.href; node.target = "_blank"; node.rel = "noopener noreferrer";
  }
  children.forEach((c) => c && node.appendChild(c));
  return node;
}

function fmtDate(iso) {
  return new Intl.DateTimeFormat(state.lang, { day: "numeric", month: "short", year: "numeric" }).format(new Date(iso));
}

async function loadJson(path, fallback) {
  try {
    const r = await fetch(path + "?v=" + Date.now());
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch (e) { return fallback; }
}

function fillSelect(sel, entries, current) {
  sel.replaceChildren(...entries.map(([value, label]) => {
    const o = el("option", { text: label }); o.value = value; return o;
  }));
  sel.value = current;
}

function applyLabels() {
  const L = t();
  document.documentElement.lang = state.lang;
  document.title = L.title;
  $("title").textContent = L.title;
  $("tagline").textContent = L.tagline;
  $("footer").textContent = L.footer;
  $("f-search").placeholder = L.search;
  $("l-hide").textContent = L.hide;
  $("more").textContent = L.more;
  $("src-intro").textContent = L.srcIntro;
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.textContent = L.tabs[b.dataset.tab];
    b.setAttribute("aria-selected", b.dataset.tab === state.tab);
  });
  document.querySelectorAll(".lang button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.lang === state.lang));
  fillSelect($("f-category"), [["", L.allCategories], ...Object.entries(L.categories)], $("f-category").value || "");
  fillSelect($("f-lang"), [["", L.allLangs], ...Object.entries(L.langs)], $("f-lang").value || "");
  fillSelect($("f-kind"), [["", L.allKinds], ...Object.entries(L.kinds)], $("f-kind").value || "");
  fillSelect($("f-period"), Object.entries(L.periods), $("f-period").value || "30");
}

function filtered() {
  const q = $("f-search").value.trim().toLowerCase();
  const cat = $("f-category").value, lang = $("f-lang").value, kind = $("f-kind").value;
  const days = parseInt($("f-period").value || "30", 10);
  const hide = $("f-hide").checked;
  const cutoff = Date.now() - days * 864e5;
  return state.articles.filter((a) =>
    new Date(a.published).getTime() >= cutoff &&
    (!cat || a.category === cat) && (!lang || a.lang === lang) && (!kind || a.kind === kind) &&
    (!hide || a.status !== "unconfirmed") &&
    (!q || (a.title + " " + a.source + " " + (a.summary || "")).toLowerCase().includes(q))
  );
}

function card(a) {
  const L = t();
  const meta = el("div", { cls: "meta" }, [
    el("span", { text: a.source }),
    el("span", { text: fmtDate(a.published) }),
    el("span", { cls: "badge", text: L.categories[a.category] || a.category }),
    el("span", { cls: "badge", text: a.lang.toUpperCase() }),
    a.kind === "primary" ? el("span", { cls: "badge primary", text: L.primary }) : null,
    a.status === "unconfirmed" ? el("span", { cls: "badge warn", text: L.unconfirmed }) : null,
    a.status === "confirmed" ? el("span", { cls: "badge", text: L.confirmed }) : null,
    a.via ? el("span", { text: `${L.via} ${a.via}` }) : null,
  ]);
  return el("article", { cls: "card" }, [
    meta,
    el("h2", {}, [el("a", { text: a.title, href: a.url })]),
    a.summary ? el("p", { text: a.summary }) : null,
  ]);
}

function renderNews() {
  const L = t();
  const list = filtered();
  const visible = list.slice(0, state.shown);
  $("count").textContent = state.updated
    ? `${L.count(list.length)} · ${L.updated} : ${new Date(state.updated).toLocaleString(state.lang)}`
    : L.never;
  $("list").replaceChildren(...visible.map(card));
  $("more").hidden = list.length <= state.shown;
}

function renderNewsletters() {
  const L = t();
  const root = $("nl-list");
  if (!state.newsletters.length) { root.replaceChildren(el("p", { cls: "muted", text: L.noNewsletters })); return; }
  const byDate = {};
  state.newsletters.forEach((n) => { (byDate[n.date] = byDate[n.date] || []).push(n); });
  root.replaceChildren(...Object.keys(byDate).sort().reverse().map((date) => {
    const items = byDate[date];
    const pick = items.find((i) => i.lang === state.lang) || items[0];
    const others = items.filter((i) => i !== pick);
    return el("div", { cls: "card" }, [
      el("div", { cls: "row" }, [
        el("strong", { text: fmtDate(date) }),
        el("span", {}, [el("a", { text: L.readNl + " (" + pick.lang.toUpperCase() + ")", href: new URL(pick.html, location.href).href }),
          ...others.map((o) => el("a", { text: " · " + o.lang.toUpperCase(), href: new URL(o.html, location.href).href }))]),
      ]),
      el("p", { text: pick.title }),
    ]);
  }));
}

function renderSources() {
  const L = t();
  $("src-list").replaceChildren(...state.health.map((s) =>
    el("div", { cls: "card" }, [
      el("div", { cls: "row" }, [
        el("strong", { text: s.name }),
        el("span", { cls: s.ok ? "status-ok" : "status-ko", text: s.ok ? `${L.ok} · ${s.items} ${L.items}` : `${L.ko} · ${s.error || ""}` }),
      ]),
    ])
  ));
}

function showTab(tab) {
  state.tab = tab;
  ["news", "newsletters", "sources"].forEach((k) => { $("tab-" + k).hidden = k !== tab; });
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab));
}

function renderAll() { applyLabels(); renderNews(); renderNewsletters(); renderSources(); }

async function init() {
  try { const saved = localStorage.getItem("lang"); if (saved === "fr" || saved === "en") state.lang = saved; else if (navigator.language.startsWith("en")) state.lang = "en"; } catch (e) {}
  const [articles, newsletters, health] = await Promise.all([
    loadJson("data/articles.json", { updated: null, articles: [] }),
    loadJson("data/newsletters.json", { items: [] }),
    loadJson("data/health.json", { sources: [] }),
  ]);
  state.articles = articles.articles; state.updated = articles.updated;
  state.newsletters = newsletters.items; state.health = health.sources;

  document.querySelectorAll(".lang button").forEach((b) => b.addEventListener("click", () => {
    state.lang = b.dataset.lang;
    try { localStorage.setItem("lang", state.lang); } catch (e) {}
    renderAll();
  }));
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  ["f-search", "f-category", "f-lang", "f-kind", "f-period", "f-hide"].forEach((id) =>
    $(id).addEventListener("input", () => { state.shown = PAGE; renderNews(); }));
  $("more").addEventListener("click", () => { state.shown += PAGE; renderNews(); });
  renderAll();
  showTab("news");
}

init();
