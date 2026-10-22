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
            "keywords": False, "aggregator": "Google News",
        })
    for b in cfg.get("bing_news", []):
        url = "https://www.bing.com/news/search?" + urlencode({"q": b["query"], "format": "rss", "setlang": b["lang"]})
        jobs.append({
            "id": b["id"], "name": "Bing Actualités: " + b["query"], "feed": url,
            "lang": b["lang"], "tier": 2, "kind": "secondary", "verify": False,
            "keywords": False, "aggregator": "Bing News",
        })
    return jobs


def make_article(entry, job, now, max_age, keywords, categories, verify_publishers):
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

    haystack = (title + " " + summary).lower()
    if job["keywords"] and not any(k in haystack for k in keywords):
        return None

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
    gl = "US" if job["lang"] == "en" else "FR"
    return "https://news.google.com/rss/search?" + urlencode(
        {"q": f"site:{domain} when:30d", "hl": job["lang"], "gl": gl, "ceid": f"{gl}:{job['lang']}"}
    )


def run_job(job, cfg, cache, now):
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
            job = {**job, "via_override": "Google News"}
            result["feed"], result["fallback"] = relay, True
        else:
            err = f"{err} ; relais Google News : {err2}"
    if parsed is None:
        result["error"] = err
        return result, []
    result["fetched"] = len(parsed.entries)
    keywords = [k.lower() for k in cfg["music_keywords"]]
    categories = {c: [w.lower() for w in ws] for c, ws in cfg["categories"].items()}
    verify_publishers = [v.lower() for v in s.get("verify_publishers", [])]
    articles = []
    for entry in parsed.entries[: s.get("max_items_per_feed", 60)]:
        a = make_article(entry, job, now, s["max_age_days"], keywords, categories, verify_publishers)
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

    with ThreadPoolExecutor(max_workers=cfg["settings"].get("workers", 8)) as pool:
        outcomes = list(pool.map(lambda j: run_job(j, cfg, cache, now), jobs))

    health = [r for r, _ in outcomes]
    fresh = [a for _, arts in outcomes for a in arts]

    previous = load_json(DATA_DIR / "articles.json", {}).get("articles", [])
    cutoff = now - timedelta(days=cfg["settings"]["max_age_days"])
    previous = [a for a in previous if parse_iso(a["published"]) >= cutoff]

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

    ok = sum(1 for h in health if h["ok"])
    print(f"{ok}/{len(health)} sources OK, {len(fresh)} articles collectés, {len(merged)} au total")
    for h in health:
        if not h["ok"]:
            print(f"  KO {h['id']}: {h['error']}")
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
