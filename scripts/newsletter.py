#!/usr/bin/env python3
"""Génère la newsletter hebdomadaire (français et anglais) avec l'API Claude.

Usage :
  python scripts/newsletter.py            ne s'exécute que le jeudi à partir de 18h (heure de Paris)
  python scripts/newsletter.py --force    génère tout de suite
  python scripts/newsletter.py --dry-run  affiche le prompt sans appeler l'API
"""
import argparse
import json
import time
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
MAX_ARTICLES = 70

EN_HEADINGS = (
    "Section titles must be in English: Editorial, Top stories, Business and sponsorship, "
    "Streaming and platforms, Live and festivals, Rights and regulation, To be verified, Key takeaways."
)

HTML_TEMPLATE = """<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{font-family:Georgia,'Times New Roman',serif;max-width:640px;margin:0 auto;padding:24px 16px;line-height:1.6;color:#1b1b1b;background:#fff}}
h1{{font-size:1.7rem;line-height:1.25}} h2{{font-size:1.2rem;margin-top:2rem;border-bottom:1px solid #ddd;padding-bottom:.3rem}}
a{{color:#0b6b4b}} footer{{margin-top:2.5rem;font-size:.85rem;color:#666}}
</style></head><body>
{body}
<footer>{footer}</footer>
</body></html>"""


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def pick_articles(articles, now_utc, days=7):
    cutoff = now_utc - timedelta(days=days)
    recent = [a for a in articles if datetime.fromisoformat(a["published"]) >= cutoff]
    recent.sort(key=lambda a: (
        a.get("status") == "unconfirmed",
        a["kind"] != "primary",
        a["tier"],
        -datetime.fromisoformat(a["published"]).timestamp(),
    ))
    recent = recent[:MAX_ARTICLES]
    return [
        {
            "title": a["title"], "source": a["source"], "kind": a["kind"],
            "status": a.get("status", "ok"), "date": a["published"][:10],
            "category": a["category"], "lang": a["lang"],
            "summary": a.get("summary", ""), "url": a["url"],
        }
        for a in recent
    ]


def build_prompts(brief, items, lang, week_label):
    system = brief + "\n\nLangue de rédaction : " + LANGS[lang] + "."
    if lang == "en":
        system += "\n" + EN_HEADINGS + " Source articles may be in French: translate and rephrase, never quote at length."
    user = (
        f"Semaine : {week_label}\n"
        f"Nombre d'articles disponibles : {len(items)}\n\n"
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
            model=MODEL, max_tokens=4500, system=system,
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
        "generationConfig": {"maxOutputTokens": 6000, "temperature": 0.4},
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
                parts = r.json()["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts).strip()
            except (KeyError, IndexError, ValueError):
                errors.append(f"{model}: réponse inattendue")
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


def write_with_fallbacks(system, user, items, lang, date_label):
    """Claude, puis Gemini (gratuit), puis compilation sans IA. Ne laisse jamais la semaine sans newsletter."""
    attempts = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        attempts.append(("Claude", call_claude))
    if os.environ.get("GEMINI_API_KEY"):
        attempts.append(("Gemini", call_gemini))
    for name, fn in attempts:
        try:
            text = fn(system, user)
            if len(text) > 400:
                print(f"[{lang}] rédigée par {name}")
                return text
            print(f"::warning title=Newsletter::{name} a renvoyé un texte trop court, on passe à la suite")
        except ProviderError as e:
            print("::warning title=Newsletter::" + re.sub(r"\s+", " ", str(e))[:600])
    print(f"[{lang}] compilation automatique sans IA")
    return compile_newsletter(items, lang, date_label)


def polish(text):
    # Garde-fou de style : pas de tirets cadratins
    return text.replace(" — ", ", ").replace("—", ", ")


def render_html(md_text, lang, site_note):
    title_match = re.search(r"^#\s+(.+)$", md_text, re.M)
    title = title_match.group(1).strip() if title_match else "Newsletter"
    body = markdown.markdown(md_text, extensions=["extra", "sane_lists"])
    return title, HTML_TEMPLATE.format(lang=lang, title=title, body=body, footer=site_note)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now_paris = datetime.now(PARIS)
    date_str = now_paris.strftime("%Y-%m-%d")
    # Deux crons UTC (16h et 17h) couvrent l'heure d'été et d'hiver : on n'agit qu'à partir de 18h
    # heure de Paris le jeudi, et jamais deux fois grâce au contrôle d'existence plus bas.
    if not (args.force or args.dry_run) and not (now_paris.weekday() == 3 and now_paris.hour >= 18):
        print(f"Pas l'heure (Paris : {now_paris:%a %H:%M}), rien à faire.")
        return

    data = load_json(DATA_DIR / "articles.json", {"articles": []})
    items = pick_articles(data["articles"], datetime.now(timezone.utc))
    if not items:
        sys.exit("Aucun article sur les 7 derniers jours, newsletter non générée.")

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
