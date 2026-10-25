# Africa Music Radar : direction visuelle et design system

## 1. Direction

**Idée centrale** : un radar de presse. Le site capte, trie et affiche ce qui bouge dans la musique africaine, toutes les 6 heures. L'identité doit ressembler à un média fiable et vivant, pas à un agrégateur automatique.

**Personnalité** : précis, crédible, vivant, panafricain, direct.
**Public** : professionnels de la musique (labels, managers, artistes, programmateurs) et fans avertis, lecture rapide sur mobile, lecture longue le jeudi.
**Anti-références** : bleu "startup", néons "tech", clichés visuels de l'Afrique (wax, safari, savane), violet, dégradés arc-en-ciel, ombres portées partout.

**Style retenu** : éditorial à grille asymétrique, dense mais lisible. Hiérarchie par les filets noirs et la typographie, pas par les cartes arrondies. Noir, papier chaud et un seul rouge.

**Signature** : le "ping". Un petit point rouge qui pulse sur tout contenu publié il y a moins de 6 h. Il rend visible la promesse du produit (le site se met à jour tout seul) et il reprend le rouge de RADAR.

## 2. Couleurs

| Rôle | Jeton | Clair | Sombre |
|---|---|---|---|
| Fond | `--surface` | #F5F2EC | #0B0B0C |
| Carte | `--surface-raised` | #FFFFFF | #23211E |
| Texte | `--text` | #131211 | #F5F2EC |
| Texte secondaire | `--text-muted` | #5A554C (6,6:1) | #A8A094 (7,6:1) |
| Filet | `--border` | #D3CCC0 | #3B3832 |
| Rouge, texte et liens | `--accent` | #C8201A (5,1:1) | #FF4B3E (5,9:1) |
| Rouge, boutons | `--accent-fill` | #C8201A, texte blanc 5,7:1 | idem |
| Repère de données | `--highlight` | #F2A71B, texte noir 9,2:1 | idem |

Règles : un seul rouge. L'ambre sert uniquement au Chiffre de la semaine et aux repères de graphiques. Jamais de texte en `paper-500` (4,0:1, insuffisant). Le rouge ne porte jamais seul une information, il est toujours accompagné d'un mot ou d'une icône.

## 3. Typographie

- **Titres** : Newsreader, graisse 500 à 700, léger resserrement. L'italique sert aux citations et au Décodeur.
- **Texte** : Public Sans 400 et 500, corps d'article à 17 px, interligne 1,6, largeur de lecture limitée à 66 caractères.
- **Étiquettes, heures, sources, chiffres** : IBM Plex Mono 12 à 14 px, capitales avec espacement de 0,08 em. C'est la voix "radar".

Échelle (ratio 1,25) : 12, 14, 16, 17, 20, 25, 31, 39, 49, 61, 76 px.

## 4. Espacement et grille

Base 4 px : 4, 8, 12, 16, 24, 32, 48, 64, 96, 128. Conteneur 1 200 px. Grille 12 colonnes, gouttière 24 px, asymétrique sur l'accueil (une à 8 colonnes, fil d'actu à 4). Sur mobile, une colonne, marges 16 px.

Filets : 1 px gris entre les articles, 2 px noirs au-dessus de chaque section. Pas d'ombre, sauf menus et fenêtres (`--shadow-overlay`).

## 5. Mouvement

- Survol : 150 ms. Ouverture : 240 ms. Apparition au scroll : 480 ms, une seule fois par élément.
- Courbe unique : `cubic-bezier(0.22, 1, 0.36, 1)`.
- Le ping dure 2,4 s en boucle. Avec `prefers-reduced-motion`, il devient un point fixe.
- Interdit : fondu montant identique sur tous les éléments, parallaxe, animations de chargement décoratives.

## 6. Composants

**Bandeau d'en-tête** : logo à gauche (noir, RADAR en rouge), rubriques au centre, bascule FR | EN à droite, recherche, bouton S'abonner. Sous le bandeau, un filet noir de 2 px.

**Ticker "Dernières 6 h"** : bande fine en mono, titres courts séparés par des filets, ping rouge devant chaque entrée récente. Défilement uniquement au survol ou au clic, jamais automatique.

**Carte d'article** (3 tailles) :
- *Une* : image 16:9, étiquette de rubrique, titre 39 à 61 px, chapô 20 px, source et heure en mono.
- *Moyenne* : image 4:3, titre 25 px, source et heure.
- *Brève* : sans image, titre 17 px en Public Sans 600, source et heure sur la ligne du dessous. Séparées par des filets.
États : survol = titre souligné en rouge (150 ms), focus = contour 2 px, visité = titre en `text-muted`.

**Étiquette de rubrique** : capsule en mono, fond transparent, bordure 1 px. Rubriques : Business, Actus, Le Décodeur, Le Chèque, Sur le terrain, Le Chiffre. Une étiquette = un mot, pas de couleur par rubrique.

**Le Chiffre de la semaine** : bloc plein `--highlight`, chiffre en Newsreader 76 px, légende en mono, source citée. C'est le seul aplat ambre du site.

**Bascule FR | EN** : deux segments en capsule, état actif plein noir, `aria-pressed`, cible tactile 44 px.

**Bouton** : primaire (fond rouge, texte blanc), secondaire (bordure noire), lien (souligné). Hauteur 48 px, rayon 6 px, texte en Public Sans 600.

**Encart newsletter** : fond `--surface-sunken`, titre en Newsreader, un champ e-mail et un bouton. Promesse concrète : "Chaque jeudi, 18 h".

## 7. À faire et à éviter

| À faire | À éviter |
|---|---|
| Une hiérarchie nette : une, moyennes, brèves | Toutes les cartes de la même taille avec la même ombre |
| Source et heure sur chaque contenu | Contenu sans origine, qui fait agrégateur anonyme |
| Titres en serif, étiquettes en mono | Une seule police sans serif partout |
| Un rouge, un ambre rare | Plusieurs accents, dégradés, néons |
| Photos d'artistes, de scènes, de studios réels | Pictogrammes génériques, clichés visuels de l'Afrique |
| Même structure en français et en anglais | Textes anglais plus courts qui cassent la grille |
| Ping réservé aux contenus de moins de 6 h | Animations en boucle partout |

## 8. Accessibilité et bilingue

- Contraste du texte d'au moins 4,5:1 (vérifié sur toutes les paires du tableau des couleurs).
- Focus visible partout, cibles tactiles de 44 px minimum.
- `lang="fr"` ou `lang="en"` sur la page, bascule qui change l'URL (`/fr/…`, `/en/…`) pour le référencement.
- Prévoir 30 % de place en plus pour les titres anglais ou français, selon la langue source.
- Dates et nombres formatés selon la langue (`1,2 M` en français, `1.2M` en anglais).

## 9. Fichiers

- `tokens.css` : variables clair et sombre, ping, focus, réduction des animations.
- `tailwind.config.js` : extension Tailwind v3 qui lit les mêmes valeurs.

Étape suivante : maquettes de l'accueil, de la carte d'article et de la page de rubrique sur ces jetons.
