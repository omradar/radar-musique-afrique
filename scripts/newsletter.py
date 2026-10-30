#!/usr/bin/env python3
"""Génère la newsletter hebdomadaire (français et anglais) avec l'API Claude.

Usage :
  python scripts/newsletter.py            ne s'exécute que le jeudi à partir de 18h (heure de Paris)
  python scripts/newsletter.py --force    génère tout de suite
  python scripts/newsletter.py --dry-run  affiche le prompt sans appeler l'API
  python scripts/newsletter.py --no-fetch ne va pas lire le texte des articles (tests hors ligne)
"""
import argparse
import difflib
import json
import time
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import markdown

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"
OUT_DIR = ROOT / "docs" / "newsletters"
BRIEF_PATH = ROOT / "config" / "newsletter_brief.md"
PARIS = ZoneInfo("Europe/Paris")
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
LANGS = {"fr": "français", "en": "English"}
MAX_CANDIDATES = 80      # articles retenus avant lecture du texte
MAX_WITH_TEXT = 45       # articles dont on a pu lire le texte, envoyés au modèle
MAX_TITLE_ONLY = 12      # articles à titre seul, envoyés comme simples signaux
SOURCE_CAP = 6           # plafond par source pour les articles sans extrait : un gros flux ne noie pas le reste
SOURCE_CAP_WITH_SUMMARY = 10  # les sources qui fournissent un extrait (InterSpace, MBW...) ont un plafond plus large
# Mots qui signalent un sujet utile à un professionnel (argent, droits, scène, plateformes)
INDUSTRY_TERMS = re.compile(
    r"sponsor|partnership|partenariat|royalt|redevance|droits? d'auteur|copyright|licen[cs]|label|\bdeal\b|signs?\b|"
    r"signe|contrat|contract|tour\b|tourn[ée]e|festival|line-?up|programmation|streams?\b|streaming|chart|classement|"
    r"revenue|revenu|invest|funding|lev[ée]e|platform|plateforme|distribut|ticket|billet|concert|management|"
    r"acquisition|launch|lance|annonce|announce|postpone|report[ée]|mon[ée]tis|monetiz|monetis", re.I)
TEXT_CHARS = 1500        # longueur de texte lue par article (le modèle reformule, ne cite pas)
FETCH_WORKERS = 6
FETCH_TIMEOUT = 12
INTERNATIONAL_SOURCES = {"Music Business Worldwide", "Billboard", "TechCrunch", "Variety", "MIDiA Research", "IFPI"}
# Les rubriques qui comptent pour des professionnels passent avant les actus culturelles
CATEGORY_WEIGHT = {"business": 0, "droits": 0, "streaming": 1, "live": 1}
# Titres sans valeur pour la newsletter : pages de tags, listings, playlists de la semaine
NOISE_TITLE = re.compile(r"^tag:|music listings and reviews|^the best .* songs right now|^infocus", re.I)
# Revues de presse génériques : gardées, mais après les articles de fond
ROUNDUP_TITLE = re.compile(r"^today in africa|^africa this week|^la revue de presse", re.I)
SKIP_FETCH_DOMAINS = ("facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com", "tiktok.com")

EN_HEADINGS = (
    "Section titles must be in English: Editorial, Top stories, Business and sponsorship, "
    "Streaming and platforms, Live and festivals, Rights and regulation, Other African news, "
    "To be verified, Key takeaways."
)

HTML_TEMPLATE = """<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&amp;family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;0,6..72,700;1,6..72,400&amp;family=Public+Sans:wght@400;500;600;700&amp;display=swap" rel="stylesheet">
<style>
:root{{--bg:#F5F2EC;--text:#131211;--muted:#5A554C;--line:#D3CCC0;--accent:#C8201A}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0B0B0C;--text:#F5F2EC;--muted:#A8A094;--line:#3B3832;--accent:#FF4B3E}}}}
*{{box-sizing:border-box}}
body{{font-family:'Public Sans',system-ui,-apple-system,'Segoe UI',sans-serif;font-size:17px;max-width:680px;margin:0 auto;padding:32px 20px 56px;line-height:1.6;color:var(--text);background:var(--bg)}}
.brand{{font-family:'Newsreader',Georgia,serif;font-weight:700;font-size:1.15rem;letter-spacing:.02em;text-transform:uppercase;padding-bottom:14px;margin-bottom:32px;border-bottom:2px solid var(--text)}}
.brand span{{color:var(--accent)}}
h1{{font-family:'Newsreader',Georgia,serif;font-weight:500;font-size:2.4rem;line-height:1.12;letter-spacing:-.015em;margin:0 0 1.5rem}}
h2,h3{{font-family:'IBM Plex Mono',ui-monospace,monospace;font-weight:600;font-size:.8125rem;letter-spacing:.08em;text-transform:uppercase;margin:2.5rem 0 1rem;padding-top:12px;border-top:2px solid var(--text)}}
p > strong:first-child{{display:block;font-family:'Newsreader',Georgia,serif;font-weight:600;font-size:1.3rem;line-height:1.25;margin-bottom:.2rem}}
hr{{border:0;border-top:1px solid var(--line);margin:2rem 0}}
a{{color:var(--accent);text-underline-offset:3px}}
a:visited{{color:var(--muted)}}
a:focus-visible{{outline:2px solid var(--text);outline-offset:3px}}
footer{{margin-top:3rem;padding-top:16px;border-top:2px solid var(--text);font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:.75rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}}
</style></head><body>
<header class="brand">{brand}</header>
{body}
<footer>{footer}</footer>
</body></html>"""


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def norm_title(title):
    t = re.sub(r"[^\w\s]", " ", title.lower())
    return re.sub(r"\s+", " ", t).strip()


def same_story(t1, t2):
    """Deux titres normalisés qui parlent du même fait (ex. 4 reprises d'une même annonce de festival)."""
    if difflib.SequenceMatcher(None, t1, t2).ratio() >= 0.6:
        return True
    w1 = {w for w in t1.split() if len(w) > 3}
    w2 = {w for w in t2.split() if len(w) > 3}
    return len(w1 & w2) >= 4 and len(w1 & w2) / max(1, min(len(w1), len(w2))) >= 0.5


def rank_key(a):
    """Ordre de priorité : confirmé, africain, article de fond, rubrique pro, avec texte, primaire, récent."""
    return (
        a.get("status") == "unconfirmed",
        a["source"] in INTERNATIONAL_SOURCES,
        bool(ROUNDUP_TITLE.search(a["title"])),
        not INDUSTRY_TERMS.search(a["title"] + " " + (a.get("summary") or "")),
        CATEGORY_WEIGHT.get(a["category"], 2),
        not a.get("summary"),
        a["kind"] != "primary",
        a["tier"],
        -datetime.fromisoformat(a["published"]).timestamp(),
    )


def pick_articles(articles, now_utc, days=7):
    """Candidats de la semaine : sans bruit, sans doublon de sujet, avec un plafond par source."""
    cutoff = now_utc - timedelta(days=days)
    recent = [
        a for a in articles
        if datetime.fromisoformat(a["published"]) >= cutoff and not NOISE_TITLE.search(a["title"])
    ]
    recent.sort(key=rank_key)
    kept, per_source = [], {}
    for a in recent:
        nt = norm_title(a["title"])
        twin = next((k for k in kept if same_story(k["_nt"], nt)), None)
        if twin:  # même sujet déjà retenu : on note qu'il est repris ailleurs
            if a["source"] != twin["source"] and a["source"] not in twin["also"]:
                twin["also"].append(a["source"])
            if not twin.get("summary") and a.get("summary"):
                twin["summary"] = a["summary"]
            continue
        slot = (a["source"], bool(a.get("summary")))
        if per_source.get(slot, 0) >= (SOURCE_CAP_WITH_SUMMARY if slot[1] else SOURCE_CAP):
            continue
        per_source[slot] = per_source.get(slot, 0) + 1
        kept.append({**a, "_nt": nt, "also": []})
        if len(kept) >= MAX_CANDIDATES:
            break
    return kept


UA = "Mozilla/5.0 (compatible; RadarMusiqueAfrique/1.0)"


def resolve_url(url):
    """Les liens Google Actualités ne mènent pas directement à l'article : on remonte à l'URL d'origine."""
    if "news.google.com" not in url:
        return url
    try:
        from googlenewsdecoder import gnewsdecoder
        res = gnewsdecoder(url, timeout=FETCH_TIMEOUT)
    except Exception:  # noqa: BLE001  (paquet absent, réseau, changement chez Google : on se rabat sur le titre)
        return None
    if isinstance(res, dict) and (res.get("success") or res.get("status")):
        return res.get("decoded_url")
    return None


def fetch_text(url):
    """Renvoie (URL d'origine, début du texte). Le texte donne au modèle des faits à reformuler."""
    import requests
    from bs4 import BeautifulSoup

    real = resolve_url(url)
    if not real:
        return None, ""
    if any(d in urlparse(real).netloc for d in SKIP_FETCH_DOMAINS):
        return real, ""
    try:
        r = requests.get(real, headers={"User-Agent": UA}, timeout=FETCH_TIMEOUT)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return real, ""
    except requests.RequestException:
        return real, ""
    soup = BeautifulSoup(r.content, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "aside", "form", "header", "noscript"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    paras = [re.sub(r"\s+", " ", p.get_text(" ")).strip() for p in root.find_all("p")]
    paras = [p for p in paras if len(p) >= 60 and "cookie" not in p.lower()]
    text = " ".join(paras)
    if len(text) > TEXT_CHARS:
        text = text[:TEXT_CHARS].rsplit(" ", 1)[0] + "..."
    return real, text


def clean_summary(summary):
    # Les flux WordPress ajoutent "The post <titre> appeared first on <site>", souvent coupé par le collecteur
    return re.sub(r"\s*The post .*$", "", summary or "", flags=re.S).strip()


def enrich(items, fetch=True):
    """Ajoute 'text' et 'depth' : texte (page lue), extrait (court résumé du flux) ou titre (rien d'autre)."""
    def job(a):
        try:
            return fetch_text(a["url"]) if fetch else (None, "")
        except Exception:  # noqa: BLE001  (une page illisible ne doit jamais bloquer la newsletter)
            return None, ""

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        results = list(pool.map(job, items))
    for a, (real, text) in zip(items, results):
        if real and "news.google.com" in a["url"]:
            a["url"] = real  # le lecteur arrive sur l'article, pas sur un lien Google de 300 caractères
        summary = clean_summary(a.get("summary"))
        if len(text) >= 200:
            a["text"], a["depth"] = text, "texte"
        elif len(summary) >= 80:
            a["text"], a["depth"] = summary, "extrait"
        else:
            a["text"], a["depth"] = "", "titre"
    return items


def finalize(items):
    """Garde les articles avec matière en priorité, quelques titres seuls comme signaux, et retire les champs internes."""
    with_text = [a for a in items if a["depth"] != "titre"][:MAX_WITH_TEXT]
    # Si la lecture des pages a échoué en masse, on ne prive pas le modèle de sujets : plus de titres seuls
    title_limit = MAX_TITLE_ONLY if len(with_text) >= 15 else MAX_CANDIDATES
    title_only = [a for a in items if a["depth"] == "titre"][:title_limit]
    print(f"Sélection : {len(with_text)} articles avec texte ({sum(a['depth'] == 'texte' for a in with_text)} pages lues), "
          f"{len(title_only)} titres seuls, sur {len(items)} candidats")
    return [
        {
            "title": a["title"], "source": a["source"], "also_reported_by": a["also"],
            "kind": a["kind"], "status": a.get("status", "ok"), "date": a["published"][:10],
            "category": a["category"], "lang": a["lang"], "depth": a["depth"],
            "text": a["text"], "url": a["url"],
        }
        for a in with_text + title_only
    ]


def build_prompts(brief, items, lang, week_label):
    system = brief + "\n\nLangue de rédaction : " + LANGS[lang] + "."
    if lang == "en":
        system += "\n" + EN_HEADINGS + " Source articles may be in French: translate and rephrase, never quote at length."
    user = (
        f"Semaine : {week_label}\n"
        f"Nombre d'articles disponibles : {len(items)}\n\n"
        "Lecture des champs : 'depth' vaut 'texte' (début de l'article, dans 'text'), 'extrait' (court résumé du flux, "
        "dans 'text') ou 'titre' (titre seul, 'text' vide). 'category' est une étiquette automatique approximative : "
        "range chaque sujet selon son contenu. 'also_reported_by' liste d'autres sources qui reprennent le même fait.\n\n"
        "Articles (JSON) :\n" + json.dumps(items, ensure_ascii=False, indent=1) +
        "\n\nRédige la newsletter complète en Markdown, sans texte avant ni après."
    )
    return system, user


class ProviderError(Exception):
    pass


def call_claude(system, user):
    import anthropic

    client = anthropic.Anthropic()
    try:
        msg = client.messages.create(
            model=MODEL, max_tokens=6000, system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIStatusError as e:
        raise ProviderError(f"Claude {e.status_code} : {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise ProviderError(f"Claude, erreur réseau : {e}") from e
    return "".join(b.text for b in msg.content if b.type == "text").strip()


GEMINI_PAUSE = int(os.environ.get("GEMINI_PAUSE", "45"))
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def gemini_candidates(headers):
    """Modèles Gemini utilisables avec cette clé, du plus récent au plus ancien (gamme flash d'abord)."""
    import requests

    forced = os.environ.get("GEMINI_MODEL")
    if forced:
        return [forced]
    found = []
    try:
        r = requests.get(f"{GEMINI_BASE}/models", params={"pageSize": 200}, headers=headers, timeout=30)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                name = m.get("name", "").replace("models/", "")
                if "generateContent" not in m.get("supportedGenerationMethods", []):
                    continue
                low = name.lower()
                if not low.startswith("gemini") or any(x in low for x in ("image", "tts", "live", "audio", "embedding", "robotics", "computer", "thinking-exp")):
                    continue
                version = re.search(r"gemini-(\d+(?:\.\d+)?)", low)
                tier = 0 if "flash" in low and "lite" not in low else 1 if "flash" in low else 2 if "pro" in low else 3
                preview = 1 if ("preview" in low or "exp" in low) else 0
                found.append((tier, -float(version.group(1)) if version else 0, preview, name))
    except Exception as e:  # noqa: BLE001
        print(f"::warning title=Gemini::liste des modèles indisponible : {e}"[:300])
    found.sort()
    names = [f[3] for f in found][:8]  # large choix : les modèles récents saturent souvent
    return names or [GEMINI_MODEL]


def call_gemini(system, user):
    import requests

    headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": 24000, "temperature": 0.4},  # large : la réflexion interne consomme aussi des jetons
    }
    errors = []
    models = gemini_candidates(headers)
    for round_no in range(3):                 # 3 tours complets, pause entre chaque
        overloaded = False
        for model in models:
            try:
                r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent", json=body, headers=headers, timeout=120)
            except requests.RequestException as e:
                errors.append(f"{model}: réseau {e}")
                continue
            if r.status_code in (429, 500, 503, 504):
                overloaded = True
                if round_no == 2:
                    errors.append(f"{model}: {r.status_code} saturé")
                continue
            if r.status_code != 200:
                if round_no == 0:
                    errors.append(f"{model}: {r.status_code} " + re.sub(r"\s+", " ", r.text)[:120])
                continue
            try:
                cand = r.json()["candidates"][0]
                text = "".join(p.get("text", "") for p in cand["content"]["parts"]).strip()
            except (KeyError, IndexError, ValueError):
                errors.append(f"{model}: réponse inattendue")
                continue
            if cand.get("finishReason") not in (None, "STOP"):
                errors.append(f"{model}: texte interrompu ({cand.get('finishReason')})")
                continue
            if text:
                print(f"Gemini : modèle utilisé = {model} (tour {round_no + 1})")
                return text
            errors.append(f"{model}: réponse vide")
        if not overloaded:
            break
        if round_no < 2:
            print(f"Gemini saturé, nouvelle tentative dans {GEMINI_PAUSE}s")
            time.sleep(GEMINI_PAUSE)
    raise ProviderError("Gemini | " + " ; ".join(errors))


COMPILE_TEXT = {
    "fr": {
        "title": "Newsletter du {d} : l'essentiel de la musique africaine",
        "intro": "Voici la sélection automatique de la semaine ({n} articles retenus). Chaque titre renvoie vers la source d'origine.",
        "sections": {"business": "Business et sponsoring", "streaming": "Streaming et plateformes",
                     "live": "Live et festivals", "droits": "Droits d'auteur et régulation", "actus": "Autres actus"},
        "verify": "À recouper",
        "verify_note": "Ces articles viennent de sources à recouper et ne sont pas confirmés.",
        "primary": "annonce de la source",
    },
    "en": {
        "title": "Newsletter of {d}: African music in brief",
        "intro": "This week's automatic selection ({n} articles). Each headline links to the original source.",
        "sections": {"business": "Business and sponsorship", "streaming": "Streaming and platforms",
                     "live": "Live and festivals", "droits": "Rights and regulation", "actus": "Other news"},
        "verify": "To be verified",
        "verify_note": "These articles come from sources that need cross-checking and are not confirmed.",
        "primary": "source announcement",
    },
}


def compile_newsletter(items, lang, date_label):
    """Version sans IA : classement par rubrique, titres et liens uniquement."""
    T = COMPILE_TEXT[lang]
    ordered = sorted(items, key=lambda i: (i["lang"] != lang, i["kind"] != "primary", i["date"]), reverse=False)
    solid = [i for i in ordered if i["status"] != "unconfirmed"]
    unconfirmed = [i for i in ordered if i["status"] == "unconfirmed"]

    def line(i):
        tag = f" ({T['primary']})" if i["kind"] == "primary" else ""
        return f"- [{i['title']}]({i['url']}) : {i['source']}, {i['date']}{tag}"

    out = [f"# {T['title'].format(d=date_label)}", "", T["intro"].format(n=len(items)), ""]
    for cat, label in T["sections"].items():
        rows = [i for i in solid if i["category"] == cat][:12]
        if rows:
            out += [f"## {label}", ""] + [line(i) for i in rows] + [""]
    if unconfirmed:
        out += [f"## {T['verify']}", "", T["verify_note"], ""] + [line(i) for i in unconfirmed[:8]] + [""]
    return "\n".join(out)


def looks_complete(text):
    """Une newsletter entière finit sur une phrase terminée ou un lien, pas au milieu d'un mot."""
    last = text.rstrip().splitlines()[-1].rstrip()
    return last.endswith((".", "!", "?", ")", ":", "»", '"', "*")) and text.count("```") % 2 == 0


def repeated_links(text):
    """Liens cités plusieurs fois : signe qu'un même sujet est traité dans deux rubriques."""
    counts = {}
    for url in re.findall(r"\]\((https?://[^)\s]+)\)", text):
        counts[url] = counts.get(url, 0) + 1
    return [u for u, n in counts.items() if n > 1]


def write_with_fallbacks(system, user, items, lang, date_label):
    """Claude, puis Gemini (gratuit), puis compilation sans IA. Ne laisse jamais la semaine sans newsletter."""
    attempts = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        attempts.append(("Claude", call_claude))
    else:
        print("::warning title=Newsletter::ANTHROPIC_API_KEY absente : la newsletter sera écrite par Gemini "
              "(gratuit, qualité moindre). Ajoute le secret dans Settings > Secrets and variables > Actions.")
    if os.environ.get("GEMINI_API_KEY"):
        attempts.append(("Gemini", call_gemini))
    for name, fn in attempts:
        try:
            text = fn(system, user)
            if len(text) > 400 and looks_complete(text):
                dupes = repeated_links(text)
                if dupes:  # un seul passage de correction : chaque sujet doit être traité une fois
                    print(f"[{lang}] {len(dupes)} source(s) citée(s) plusieurs fois, nouvelle rédaction demandée")
                    retry = user + (
                        "\n\nCorrection : dans ta version précédente, ces liens étaient cités plusieurs fois "
                        "(un même sujet traité dans plusieurs rubriques) :\n" + "\n".join(dupes) +
                        "\nTraite chaque sujet une seule fois, dans la rubrique la plus utile."
                    )
                    try:
                        better = fn(system, retry)
                        if len(better) > 400 and looks_complete(better) and len(repeated_links(better)) < len(dupes):
                            text = better
                    except ProviderError:
                        pass
                print(f"[{lang}] rédigée par {name}")
                return text
            print(f"::warning title=Newsletter::{name} a renvoyé un texte trop court ou coupé, on passe à la suite")
        except ProviderError as e:
            print("::warning title=Newsletter::" + re.sub(r"\s+", " ", str(e))[:600])
    print(f"[{lang}] compilation automatique sans IA")
    return compile_newsletter(items, lang, date_label)


def polish(text):
    # Garde-fou de style : pas de tirets cadratins
    text = text.replace(" — ", ", ").replace("—", ", ")
    # Garde-fou de forme : le modèle ferme parfois un lien avec "]" ou "." au lieu de ")"
    def close(m):
        return f"]({m.group(1)})" + ("." if m.group(2).endswith(".") else "")
    return re.sub(r"\]\((https?://[^)\s\]]+?)([\].]+)(?=\s|$)", close, text)


def render_html(md_text, lang, site_note):
    title_match = re.search(r"^#\s+(.+)$", md_text, re.M)
    title = title_match.group(1).strip() if title_match else "Newsletter"
    body = markdown.markdown(md_text, extensions=["extra", "sane_lists"])
    brand = re.sub(r"\b(Radar)\b", r"<span>\1</span>", site_note)  # « Radar » en rouge (charte graphique)
    return title, HTML_TEMPLATE.format(lang=lang, title=title, brand=brand, body=body, footer=site_note)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-fetch", action="store_true", help="ne lit pas le texte des articles (tests hors ligne)")
    args = ap.parse_args()

    now_paris = datetime.now(PARIS)
    date_str = now_paris.strftime("%Y-%m-%d")
    # Deux crons UTC (16h et 17h) couvrent l'heure d'été et d'hiver : on n'agit qu'à partir de 18h
    # heure de Paris le jeudi, et jamais deux fois grâce au contrôle d'existence plus bas.
    if not (args.force or args.dry_run) and not (now_paris.weekday() == 3 and now_paris.hour >= 18):
        print(f"Pas l'heure (Paris : {now_paris:%a %H:%M}), rien à faire.")
        return

    data = load_json(DATA_DIR / "articles.json", {"articles": []})
    candidates = pick_articles(data["articles"], datetime.now(timezone.utc))
    if not candidates:
        sys.exit("Aucun article sur les 7 derniers jours, newsletter non générée.")
    items = finalize(enrich(candidates, fetch=not args.no_fetch))

    week_start = (now_paris - timedelta(days=7)).strftime("%d/%m/%Y")
    week_label = f"du {week_start} au {now_paris:%d/%m/%Y}"
    brief = BRIEF_PATH.read_text(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index_path = DATA_DIR / "newsletters.json"
    index = load_json(index_path, {"items": []})

    for lang in LANGS:
        html_path = OUT_DIR / f"{date_str}-{lang}.html"
        if html_path.exists() and not args.force:
            print(f"{html_path.name} existe déjà, ignoré.")
            continue
        system, user = build_prompts(brief, items, lang, week_label)
        if args.dry_run:
            print(f"===== {lang} : système =====\n{system}\n===== utilisateur ({len(items)} articles) =====\n{user[:1500]}...")
            continue
        text = polish(write_with_fallbacks(system, user, items, lang, now_paris.strftime("%d/%m/%Y")))
        footer = "Radar Musique Afrique" if lang == "fr" else "Africa Music Radar"
        title, html_doc = render_html(text, lang, footer)
        (OUT_DIR / f"{date_str}-{lang}.md").write_text(text, encoding="utf-8")
        html_path.write_text(html_doc, encoding="utf-8")
        index["items"] = [i for i in index["items"] if not (i["date"] == date_str and i["lang"] == lang)]
        index["items"].append({
            "date": date_str, "lang": lang, "title": title,
            "html": f"newsletters/{date_str}-{lang}.html", "md": f"newsletters/{date_str}-{lang}.md",
        })
        print(f"Newsletter {lang} écrite : {html_path.name}")

    if not args.dry_run:
        index["items"].sort(key=lambda i: (i["date"], i["lang"]), reverse=True)
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
