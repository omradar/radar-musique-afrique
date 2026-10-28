#!/usr/bin/env python3
"""Collecte les actualités depuis les flux RSS, Google Actualités et Bing Actualités.

Sortie :
  docs/data/articles.json   articles gardés (90 jours glissants par défaut)
  docs/data/health.json     état de chaque source au dernier passage
  data/feed_cache.json      flux découverts automatiquement (évite de les rechercher à chaque fois)
"""
import calendar
import difflib
import hashlib
import html
import json
import re
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "sources.yml"
DATA_DIR = ROOT / "docs" / "data"
CACHE_PATH = ROOT / "data" / "feed_cache.json"
UA = "Mozilla/5.0 (compatible; RadarMusiqueAfrique/1.0)"
SUMMARY_MAX = 280  # extrait court : on renvoie vers la source, on ne republie pas l'article
RELAY_TERMS = ["music", "musique", "concert", "festival", "streaming", "artiste", "artist"]
COMMON_PATHS = ["/feed", "/feed/", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml"]
TRACKING_PREFIXES = ("utm_", "mc_")
TRACKING_KEYS = {"fbclid", "gclid", "ref"}


# ---------- utilitaires ----------

def http_get(url, timeout):
    try:
        r = requests.get(
            url,
            headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*"},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.content, None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"[:200]


def clean_text(raw):
    if not raw:
        return ""
    text = BeautifulSoup(raw, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def shorten(text, n):
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip(",;:.") + "..."


def normalize_url(url):
    p = urlparse(url)
    query = [
        (k, v)
        for k, v in parse_qsl(p.query)
        if not k.lower().startswith(TRACKING_PREFIXES) and k.lower() not in TRACKING_KEYS
    ]
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", urlencode(query), ""))


def norm_title(title):
    t = re.sub(r"[^\w\s]", " ", title.lower())
    return re.sub(r"\s+", " ", t).strip()


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def entry_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return None


def parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------- filtres : actualités africaines et musicales uniquement ----------

def term_regex(terms):
    """Regex de mots entiers (pluriel en s ou x accepté). 'clip' ne matche donc plus 'éclipse'."""
    parts = sorted({re.escape(t.lower().replace("’", "'")) for t in terms}, key=len, reverse=True)
    if not parts:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?:s|x)?(?!\w)")


def prep(text):
    return text.lower().replace("’", "'")


class Gates:
    """Trois portes : pas de spam, de la musique, de l'Afrique (sauf pour les médias africains)."""

    def __init__(self, cfg):
        f = cfg.get("filters", {})
        self.music_strong = term_regex(cfg["music_keywords"])
        self.music_weak = term_regex(f.get("ambiguous_music_keywords", []))
        self.non_music = term_regex(f.get("non_music_terms", []))
        self.africa = term_regex(f.get("africa_terms", []))
        self.artists = term_regex(f.get("african_artists", []))
        self.african_publishers = term_regex(f.get("african_publishers", []))
        self.blocked = [re.compile(p, re.I) for p in f.get("blocked_title_patterns", [])]
        self.min_title = f.get("min_title_chars", 15)
        self.rejected = []  # (raison, source, titre) pour régler les filtres
        self.counts = {}

    def reject(self, reason, source, title):
        self.counts[reason] = self.counts.get(reason, 0) + 1
        if len(self.rejected) < 400:
            self.rejected.append({"reason": reason, "source": source, "title": title[:140]})
        return reason

    def is_junk(self, title, url):
        if len(title.strip(" -|")) < self.min_title or "#comment-" in url or "/comment-page" in url:
            return True
        return any(p.search(title) for p in self.blocked)

    def music_ok(self, text):
        if self.music_strong and self.music_strong.search(text):
            return True
        if self.artists and self.artists.search(text):  # un artiste africain connu vaut signal musical
            return True
        # mot ambigu (festival, label, streaming...) : accepté seulement sans signal sport, cinéma, etc.
        return bool(self.music_weak and self.music_weak.search(text)) and not (
            self.non_music and self.non_music.search(text)
        )

    def africa_ok(self, text):
        if self.africa and self.africa.search(text):
            return True
        return bool(self.artists and self.artists.search(text))

    def check(self, title, summary, url, source, needs_music, africa_exempt):
        """Renvoie None si l'article passe, sinon la raison du rejet."""
        if self.is_junk(title, url):
            return self.reject("spam", source, title)
        text = prep(title + " " + summary)
        if needs_music and not self.music_ok(text):
            return self.reject("pas musique", source, title)
        publisher_ok = bool(self.african_publishers and self.african_publishers.search(prep(source)))
        if not (africa_exempt or publisher_ok) and not self.africa_ok(text):
            return self.reject("pas Afrique", source, title)
        return None


# ---------- flux ----------

def discover_feed(homepage, timeout, cache):
    if homepage in cache:
        return cache[homepage]
    candidates = []
    content, _ = http_get(homepage, timeout)
    if content:
        soup = BeautifulSoup(content, "html.parser")
        for link in soup.find_all("link", href=True):
            rel = link.get("rel") or []
            rel = " ".join(rel) if isinstance(rel, list) else rel
            ctype = link.get("type") or ""
            if "alternate" in rel and ("rss" in ctype or "atom" in ctype):
                candidates.append(urljoin(homepage, link["href"]))
    base = homepage.rstrip("/")
    candidates += [base + p for p in COMMON_PATHS]
    for url in candidates[:9]:
        data, _ = http_get(url, timeout)
        if data and feedparser.parse(data).entries:
            cache[homepage] = url
            return url
    return None


def build_jobs(cfg):
    jobs = []
    for s in cfg["sources"]:
        jobs.append({**s, "aggregator": None})
    for g in cfg.get("google_news", []):
        url = "https://news.google.com/rss/search?" + urlencode(
            {"q": g["query"] + " when:7d", "hl": g["hl"], "gl": g["gl"], "ceid": g["ceid"]}
        )
        jobs.append({
            "id": g["id"], "name": "Google Actualités: " + g["query"], "feed": url,
            "lang": g["hl"], "tier": 2, "kind": "secondary", "verify": False,
            "keywords": False, "africa": False, "aggregator": "Google News",
        })
    for b in cfg.get("bing_news", []):
        url = "https://www.bing.com/news/search?" + urlencode({"q": b["query"], "format": "rss", "setlang": b["lang"]})
        jobs.append({
            "id": b["id"], "name": "Bing Actualités: " + b["query"], "feed": url,
            "lang": b["lang"], "tier": 2, "kind": "secondary", "verify": False,
            "keywords": False, "africa": False, "aggregator": "Bing News",
        })
    return jobs


def make_article(entry, job, now, max_age, gates, categories, verify_publishers):
    title = clean_text(entry.get("title", ""))
    link = entry.get("link")
    published = entry_date(entry)
    if not title or not link or not published:  # la date de publication est obligatoire
        return None
    if published > now + timedelta(days=1) or now - published > timedelta(days=max_age):
        return None

    source_name, source_id, verify = job["name"], job["id"], job["verify"]
    summary = ""
    via = job.get("via_override") or job["aggregator"]
    if via:
        publisher = (entry.get("source") or {}).get("title") or via
        suffix = " - " + publisher
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
        if job["aggregator"]:  # recherche libre : l'éditeur est celui indiqué par Google ou Bing
            source_name, source_id = publisher, slug(publisher) or job["id"]
            verify = slug(publisher) in verify_publishers or any(v in slug(publisher) for v in verify_publishers)
    else:
        summary = shorten(clean_text(entry.get("summary", "")), SUMMARY_MAX)

    # Un agrégateur (Google, Bing) renvoie n'importe quoi : musique et Afrique obligatoires.
    needs_music = bool(job["keywords"] or job["aggregator"])
    if gates.check(title, summary, link, source_name, needs_music, bool(job.get("africa"))):
        return None
    haystack = prep(title + " " + summary)

    category = "actus"
    for cat, words in categories.items():
        if any(w in haystack for w in words):
            category = cat
            break

    return {
        "id": hashlib.sha1(normalize_url(link).encode()).hexdigest()[:16],
        "title": title,
        "url": link,
        "summary": summary,
        "source": source_name,
        "source_id": source_id,
        "via": via,
        "lang": job["lang"],
        "kind": job["kind"] if not job["aggregator"] else "secondary",
        "tier": job["tier"],
        "verify": verify,
        "category": category,
        "published": published.isoformat(),
    }


def fetch_feed(url, timeout):
    data, err = http_get(url, timeout)
    if err:
        return None, err
    parsed = feedparser.parse(data)
    if not parsed.entries:
        return None, "flux vide ou illisible"
    return parsed, None


def google_site_url(job):
    """Relais pour les sites sans flux ou qui bloquent GitHub : Google Actualités restreint au domaine."""
    domain = urlparse(job["homepage"]).netloc.replace("www.", "")
    gl = {"en": "US", "pt": "PT", "sw": "KE"}.get(job["lang"], "FR")
    # Pour les sites généralistes, Google fait le tri musique à notre place (le titre seul ne suffit pas)
    terms = " (" + " OR ".join(RELAY_TERMS) + ")" if job.get("keywords") else ""
    return "https://news.google.com/rss/search?" + urlencode(
        {"q": f"site:{domain}{terms} when:30d", "hl": job["lang"], "gl": gl, "ceid": f"{gl}:{job['lang']}"}
    )


def run_job(job, cfg, cache, now, gates):
    s = cfg["settings"]
    result = {
        "id": job["id"], "name": job["name"], "ok": False, "items": 0, "fetched": 0,
        "feed": job.get("feed"), "fallback": False, "error": None,
    }
    feed_url = job.get("feed")
    if not feed_url and job.get("homepage"):
        feed_url = discover_feed(job["homepage"], s["timeout"], cache)
    result["feed"] = feed_url
    parsed, err = None, "aucun flux trouvé (site sans RSS ou qui bloque GitHub)"
    if feed_url:
        parsed, err = fetch_feed(feed_url, s["timeout"])
    if parsed is None and job.get("homepage") and not job["aggregator"]:
        relay = google_site_url(job)
        parsed, err2 = fetch_feed(relay, s["timeout"])
        if parsed is not None:
            job = {**job, "via_override": "Google News"}  # le filtre par mots-clés reste appliqué au titre
            result["feed"], result["fallback"] = relay, True
        else:
            err = f"{err} ; relais Google News : {err2}"
    if parsed is None:
        result["error"] = err
        return result, []
    result["fetched"] = len(parsed.entries)
    categories = {c: [w.lower() for w in ws] for c, ws in cfg["categories"].items()}
    verify_publishers = [v.lower() for v in s.get("verify_publishers", [])]
    articles = []
    for entry in parsed.entries[: s.get("max_items_per_feed", 60)]:
        a = make_article(entry, job, now, s["max_age_days"], gates, categories, verify_publishers)
        if a:
            articles.append(a)
    result["ok"] = True
    result["items"] = len(articles)
    return result, articles


# ---------- fusion, dédoublonnage, statut ----------

def dedupe(articles):
    """Garde un seul exemplaire par URL et par titre, en préférant primaire puis tier bas."""
    ranked = sorted(articles, key=lambda a: (a["kind"] != "primary", a["verify"], a["tier"]))
    seen_ids, seen_titles, kept = set(), set(), []
    for a in ranked:
        nt = norm_title(a["title"])
        if a["id"] in seen_ids or nt in seen_titles:
            continue
        seen_ids.add(a["id"])
        seen_titles.add(nt)
        kept.append(a)
    return kept


def compute_status(articles):
    """Un article d'une source à recouper est 'unconfirmed' tant qu'aucune autre source ne le reprend."""
    solid = [
        (norm_title(a["title"]), a["source_id"], parse_iso(a["published"]))
        for a in articles if not a["verify"]
    ]
    for a in articles:
        if not a["verify"]:
            a["status"] = "ok"
            continue
        nt, ts = norm_title(a["title"]), parse_iso(a["published"])
        confirmed = any(
            sid != a["source_id"]
            and abs(ts - t_ts) <= timedelta(days=14)
            and difflib.SequenceMatcher(None, nt, t).ratio() >= 0.6
            for t, sid, t_ts in solid
        )
        a["status"] = "confirmed" if confirmed else "unconfirmed"
    return articles


def keep_existing(a, sources_by_id, gates):
    src = sources_by_id.get(a["source_id"])
    needs_music = src["keywords"] if src else True  # source inconnue = éditeur vu via Google ou Bing
    africa_exempt = bool(src and src.get("africa"))
    return gates.check(a["title"], a.get("summary", ""), a["url"], a["source"], needs_music, africa_exempt) is None


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def main():
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    cache = load_json(CACHE_PATH, {})
    jobs = build_jobs(cfg)
    gates = Gates(cfg)

    with ThreadPoolExecutor(max_workers=cfg["settings"].get("workers", 8)) as pool:
        outcomes = list(pool.map(lambda j: run_job(j, cfg, cache, now, gates), jobs))

    health = [r for r, _ in outcomes]
    fresh = [a for _, arts in outcomes for a in arts]

    previous = load_json(DATA_DIR / "articles.json", {}).get("articles", [])
    cutoff = now - timedelta(days=cfg["settings"]["max_age_days"])
    previous = [a for a in previous if parse_iso(a["published"]) >= cutoff]
    # Les filtres s'appliquent aussi à l'historique : un article accepté hier par l'ancienne règle part.
    sources_by_id = {src["id"]: src for src in cfg["sources"]}
    before = len(previous)
    previous = [a for a in previous if keep_existing(a, sources_by_id, gates)]
    purged = before - len(previous)

    merged = dedupe(fresh + previous)  # les nouveautés passent avant l'historique
    merged = compute_status(merged)
    merged.sort(key=lambda a: a["published"], reverse=True)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    (DATA_DIR / "articles.json").write_text(
        json.dumps({"updated": now.isoformat(), "count": len(merged), "articles": merged}, ensure_ascii=False),
        encoding="utf-8",
    )
    (DATA_DIR / "health.json").write_text(
        json.dumps({"updated": now.isoformat(), "sources": health}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    (ROOT / "data" / "rejected.json").write_text(
        json.dumps({"updated": now.isoformat(), "counts": gates.counts, "sample": gates.rejected}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    ok = sum(1 for h in health if h["ok"])
    print(f"{ok}/{len(health)} sources OK, {len(fresh)} articles collectés, {len(merged)} au total")
    print(f"Filtres : {gates.counts} ; {purged} anciens articles retirés de l'historique")
    for h in health:
        if not h["ok"]:
            print(f"  KO {h['id']}: {h['error']}")
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
