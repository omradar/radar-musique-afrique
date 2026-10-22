# Radar Musique Afrique / Africa Music Radar

Site de veille sur la musique africaine et son industrie (business, streaming, live, droits, sponsoring, actus).

- Collecte automatique toutes les 6 heures : flux RSS, Google Actualités, Bing Actualités
- Site statique bilingue (français et anglais) hébergé sur GitHub Pages
- Newsletter hebdomadaire rédigée par l'API Claude chaque jeudi à 18h (heure de Paris), en français et en anglais

## Mise en ligne en 6 étapes

1. Crée un dépôt GitHub (public pour des Actions et un Pages gratuits), puis envoie-y tout le contenu de ce dossier.
2. Dans le dépôt : Settings, Pages, "Deploy from a branch", branche `main`, dossier `/docs`.
3. Dans Settings, Actions, General, Workflow permissions : choisis "Read and write permissions".
4. Dans Settings, Secrets and variables, Actions : crée le secret `ANTHROPIC_API_KEY` avec ta clé de la Console Anthropic.
5. Onglet Actions : lance à la main "Mise à jour des actus" (Run workflow). Regarde ensuite l'onglet "Sources" du site : il montre quelles sources ont un flux qui marche.
6. Quand le site contient des articles, lance à la main "Newsletter du jeudi" pour tester une édition. Ensuite, c'est automatique.

## Comment ça marche

| Élément | Fichier |
| --- | --- |
| Sources, mots-clés, catégories | `config/sources.yml` |
| Collecteur | `scripts/collect.py` |
| Consignes éditoriales de la newsletter (ton, structure, règles de rigueur) | `config/newsletter_brief.md` |
| Générateur de newsletter | `scripts/newsletter.py` |
| Site | `docs/index.html`, `docs/app.js`, `docs/style.css` |
| Automatisations | `.github/workflows/` |

### Règles issues du document de Kalz

- Source primaire ou presse qui relaie : badge sur chaque article.
- Sources à recouper (TechLabari, Senego, Seneweb) : un article qui n'apparaît que chez elles est marqué "Non confirmé". Il devient "Recoupé" dès qu'une autre source publie un titre proche dans les 14 jours.
- Date de publication obligatoire : un article sans date est écarté.
- Fraîcheur : 90 jours maximum (réglable dans `sources.yml`).
- Dans la newsletter, les articles non confirmés vont uniquement dans la rubrique "À recouper".

### Test de recette

Après le premier passage, cherche dans le site les cinq sujets déjà traités (financement de la culture, filtre IA de Deezer, Audiomack Night Plan, 286 M$ non collectés, Youssou Ndour à Bercy). Les anciens articles peuvent avoir dépassé la fenêtre des flux RSS, qui ne contiennent en général que les dernières publications. Un test plus pertinent : vérifier que les nouveaux articles de ces mêmes sources arrivent bien.

## Ajouter ou retirer une source

Édite `config/sources.yml`. Si une source n'a pas d'URL `feed`, le collecteur cherche le flux tout seul. Si rien n'est trouvé, la source apparaît en erreur dans l'onglet "Sources" : renseigne alors l'URL du flux à la main, ou passe par un flux Google Actualités.

## Limites connues

- Les flux n'ont pas été testés avant la mise en ligne : certains sites n'ont pas de RSS ou le bloquent. Le premier passage donne la vérité.
- Google Actualités et Bing donnent des liens de redirection, c'est normal.
- LinkedIn et les sites payants ne sont pas collectés.
- Le site affiche titre, extrait court (280 caractères) et lien. Ne le change pas pour republier des articles entiers.
- GitHub peut retarder un déclenchement planifié de quelques minutes, parfois plus aux heures de pointe. C'est pour cela que la newsletter accepte toute heure à partir de 18h le jeudi.

## Envoi par email (non inclus)

La newsletter est publiée sur le site en HTML (`docs/newsletters/AAAA-MM-JJ-fr.html`). Pour l'envoyer par email, copie-la dans un outil comme Buttondown, Brevo ou Resend, ou ajoute une étape d'envoi dans `newsletter.yml`.

## Test en local

```bash
pip install -r requirements.txt
python scripts/collect.py
python scripts/newsletter.py --dry-run     # affiche le prompt sans appeler l'API
ANTHROPIC_API_KEY=... python scripts/newsletter.py --force
python -m http.server -d docs 8000         # site sur http://localhost:8000
```
