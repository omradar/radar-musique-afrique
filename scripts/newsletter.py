#!/usr/bin/env python3
"""Génère la newsletter hebdomadaire (français et anglais) avec l'API Claude.

Usage :
  python scripts/newsletter.py            ne s'exécute que le jeudi à partir de 18h (heure de Paris)
  python scripts/newsletter.py --force    génère tout de suite
  python scripts/newsletter.py --dry-run  affiche le prompt sans appeler l'API
"""
import argparse
import json
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


def call_claude(system, user):
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY manquante (secret GitHub à créer, voir le README).")
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL, max_tokens=4500, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if b.type == "text").strip()


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
        text = polish(call_claude(system, user))
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
