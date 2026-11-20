# horizon-analyzer

Rejoue en production les parcours critiques d'Horizon (connexion, création de projet, import
d'un modèle 3D, déplacement dans la scène...) décrits dans un fichier YAML ou JSON, et produit
un rapport feature par feature.

```
horizon-prod-critical: 17 feature(s), run 20261119-1647-62e0
  OK   F1-login                    0.8s  Connexion à l'éditeur avec le compte de test
  OK   F4-create-project           1.3s  Créer un projet de jeu
  OK   EDITOR-viewport             4.4s  Le viewport 3D démarre (Bevy sur WebGPU)
  OK   F5-import-mesh              0.7s  Importer un modèle 3D (.glb)
  OK   F8-place-and-move           2.7s  Placer le modèle dans la scène et le déplacer
  OK   F8-rotate-scale             0.3s  Tourner et redimensionner le modèle
  OK   EDITOR-undo-redo            0.2s  Annuler puis rétablir une modification
  OK   F7-add-light                0.3s  Ajouter une lumière directionnelle
  OK   EDITOR-add-camera           0.5s  Ajouter une caméra et la placer devant la scène
  OK   EDITOR-primitives           1.3s  Créer, dupliquer et supprimer une primitive
  OK   EDITOR-gizmo-tools          0.1s  Changer d'outil de transformation (rotation, échelle, translation)
  OK   F17-play-in-editor          2.7s  Lancer le jeu dans l'éditeur et vérifier qu'il s'affiche
  OK   F15-publish                 1.4s  Publier le jeu (payant, 10 pièces)
  OK   LAUNCHER-login              0.8s  Connexion au launcher
  OK   F18-buy-coins               8.1s  Acheter 500 pièces par Stripe (carte de test)
  OK   F18-unlock-game             0.8s  Débloquer le jeu publié avec des pièces
  OK   F17-play-launcher           4.3s  Lancer le jeu depuis le launcher et vérifier qu'il s'affiche
horizon-prod-critical [20261119-1647-62e0]: 17 passed in 33.75s
```

`scenarios/critical.yaml` suit un créateur puis un joueur : édition 3D (import, transformations,
lumière, caméra, primitives, undo/redo), lancement du jeu dans l'éditeur, publication d'un jeu
payant, achat de pièces par Stripe (carte de test), déblocage du jeu avec ces pièces et lancement
dans le launcher. Le jeu « s'affiche » quand son canvas dessine autre chose qu'un fond uni
(vérification `rendered`) ; la caméra est placée en (0, 1, 6) pour cadrer le cube.

`scenarios/engine.yaml` teste le moteur lui-même : un vrai modèle importé (l'ange
« cemetery_angel », glTF texturé de 35 Mo), un sol, un cube et une sphère dorés et lisses
(reflets), une lumière qui projette des ombres, un fond de caméra coloré, un script construit
dans l'éditeur de nœuds (On Every Frame → Rotate) attaché à l'ange et au cube, et un script
écrit par l'assistant IA à partir d'un prompt, attaché à la sphère. Il contient aussi deux cas
qui ne fonctionnent pas dans Horizon, écrits comme des features normales : un modèle corrompu et
une texture ordinaire en skybox. Ils sortent KO exprès (16 OK, 2 KO), avec la cause dans le rapport. Le jeu lancé doit
avoir le bleu choisi pour couleur dominante (`dominant_color`) et bouger d'une capture à l'autre
(`animated`).

**Tout lancer** (Windows) : `.\run-all.ps1` installe ce qu'il faut au premier lancement, puis
enchaîne le smoke, le parcours critique et le scénario moteur. Le détail de chaque feature, la lecture du rapport et
le dépannage sont dans [docs/scenarios.md](docs/scenarios.md). Pour écrire un scénario :
[docs/ecrire-un-scenario.md](docs/ecrire-un-scenario.md).

## Installation

Python 3.11 ou plus récent.

```sh
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS : source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
copy .env.example .env          # puis renseigner le compte de test
```

`.env` contient les identifiants du compte de test et n'est jamais commité.

## Utilisation

```sh
horizon-analyzer run scenarios/critical.yaml            # navigateur visible, vrai GPU
horizon-analyzer run scenarios/smoke.yaml --headless    # rapide, sans fenêtre
horizon-analyzer run scenarios/critical.yaml --tags 3d  # seulement ces tags (+ leurs dépendances)
horizon-analyzer run scenarios/critical.yaml --only F5-import-mesh
horizon-analyzer run scenarios/critical.yaml --safe-only   # rien qui écrive en prod
horizon-analyzer run scenarios/critical.yaml --slow-mo 500 # pour suivre à l'œil
horizon-analyzer run scenarios/critical.yaml --no-cache    # retélécharger le wasm (cache : runs/.cache/)
horizon-analyzer validate scenarios/critical.yaml       # vérifie le fichier sans navigateur
horizon-analyzer schema -o scenarios/horizon-analyzer.schema.json
```

Code de sortie : 0 si tout passe, 1 si une feature échoue ou est bloquée, 2 si le fichier est
invalide.

Chaque run écrit dans `runs/<run id>/` :

| Fichier | Contenu |
| --- | --- |
| `report.html` | Le rapport à ouvrir : une ligne par feature, étapes, captures, erreurs console |
| `report.json` | Le même contenu, pour un autre outil |
| `junit.xml` | Pour GitHub Actions ou un autre CI |
| `trace.zip` | Trace Playwright complète : `playwright show-trace runs/<id>/trace.zip` |
| `failures/<feature>.png` | La page au moment de l'échec |
| `screenshots/` | Les captures demandées par les scénarios |

Pour être prévenu d'un échec, mettre un webhook Discord ou Slack dans `HORIZON_WEBHOOK_URL`
(ou `--webhook`).

## Écrire un scénario

> **Guide complet** : [docs/ecrire-un-scenario.md](docs/ecrire-un-scenario.md). Il détaille chaque champ
> (suite, feature, `teardown`, `cleanup`…), chaque action avec ses options, les cibles, les vérifications,
> les pièges YAML et un exemple complet. Cette section en est le résumé.

Un fichier = une suite de features, exécutées dans l'ordre sur la même page (la connexion de la
première sert aux suivantes). Une feature = une liste d'étapes. Une étape = une action et ses
options. Les fichiers de `scenarios/` déclarent le JSON Schema : VS Code (extension YAML de Red
Hat) propose alors l'autocomplétion et souligne les erreurs.

```yaml
suite: horizon-prod-critical
base_urls:
  editor: https://editor.play-horizon.games
timeout: 15s
fail_on_console: ["panicked at"]

features:
  - id: F1-login
    name: Connexion avec le compte de test
    tags: [critical, smoke]
    steps:
      - goto: ${base.editor}/
      - fill: { label: Email }
        value: ${env.HORIZON_EMAIL}
      - click: { role: button, name: Sign In }
        expect_response: { url: "**/login", method: POST, status: 2xx }
      - expect: { target: { role: heading, name: Welcome back }, visible: true }
```

### Features

| Champ | Rôle |
| --- | --- |
| `id`, `name` | Identifiant (repris du beta test plan : F1, F5...) et libellé |
| `tags` | Pour filtrer avec `--tags` |
| `depends_on` | Features déclarées avant ; si l'une ne passe pas, celle-ci est sautée |
| `mutating` | Écrit en prod ; exclue par `--safe-only` |
| `requires_webgpu` | Marquée « bloquée » (et non en échec) si le navigateur n'a pas de WebGPU |
| `teardown` | Étapes jouées juste après la feature, qu'elle passe ou échoue, pour remettre la page en ordre (fermer un dialogue, arrêter le jeu). Elles s'affichent dans le rapport comme `teardown: …`. Si elles échouent, une feature qui passait devient KO |
| `cleanup` | Étapes qui défont ce que la feature a créé. Elles tournent en fin de run, de la dernière feature à la première, même après un échec |

### Actions

| Action | Exemple | Options |
| --- | --- | --- |
| `goto` | `goto: ${base.editor}/` | `expect_response` |
| `click` | `click: { role: button, name: OK }` | `button: right` (menu contextuel), `position: { x, y }`, `expect_response`, `force`, `timeout` |
| `select` | `select: { role: treeitem, has_text: Camera }` | clique seulement si l'élément n'est pas déjà sélectionné (`aria-selected`) : un clic sur une ligne sélectionnée de la hiérarchie la désélectionne |
| `hover` | `hover: { text: Mon jeu }` | `timeout` |
| `fill` | `fill: { label: Email }` + `value:` | `timeout` |
| `press` | `press: Enter` | `target` (sinon : l'élément qui a le focus) |
| `upload` | `upload: { css: "input[type=file]" }` + `files: [fixtures/a.glb]` | chemins relatifs au fichier |
| `drag` | `drag: { text: cube }` + `to: { id: canvas }` | `to_position: { x, y }` (point d'arrivée dans `to`), `steps: 12` (glissé en 12 petits mouvements de souris : obligatoire dans l'éditeur de nœuds, qui ignore un saut unique), `timeout` |
| `choose` | `choose: { css: select }` + `option: float` | une option d'un `<select>`, par sa valeur ou son libellé |
| `wait` | `wait: 2s` | à éviter : préférer un `expect` |
| `reload` | `reload: true` | |
| `screenshot` | `screenshot: apres-import` | `of` (une cible au lieu de la page) |
| `store` | `store: project_id` + `url_pattern: "id=(\\w+)"` | ou `text_of: <cible>`, ou `js: "() => fetch(...)..."` ; réutilisable en `${var.project_id}` |
| `expect` | voir ci-dessous | |

`expect_response: { url, method, status, timeout }` exige que l'action déclenche une réponse
réseau : `url` est un glob (`*` et `**` = n'importe quoi), `status` un code (`201`) ou une
classe (`2xx`).

### Cibles

Une seule base, par ordre de préférence : `testid`, `role` (+ `name`), `label`, `text`,
`placeholder`, `title`, `id`, `css`. Puis, pour affiner :

- `exact: true` : le texte doit correspondre exactement (sinon : « contient »).
- `within: <cible>` : chercher dans un autre élément.
- `has_text: ...` / `has: <cible>` : garder les éléments qui contiennent ce texte ou cet élément.
- `nth: first | last | 2` : choisir parmi plusieurs. Sans `nth`, plusieurs résultats = erreur
  (c'est voulu : un clic ne doit jamais tomber sur le mauvais bouton).
- `frame: "<css de l'iframe>"` : chercher dans une iframe, par exemple le formulaire Stripe
  (`iframe[src*='js.stripe.com/v3/elements-inner']:visible`).

Les ancres YAML évitent de répéter une cible longue :

```yaml
- fill: &position_x { role: spinbutton, name: X, within: { css: div.flex-col, has: { css: ":scope > span", has_text: position }, nth: last } }
  value: "5"
- expect: { target: *position_x, value: "5" }
```

### Vérifications (`expect`)

Toutes réessaient jusqu'à `timeout` (défaut : celui de la suite).

| Sur une `target` | Sur la page |
| --- | --- |
| `visible: true/false` | `url: "**/editor?id=*"` (glob) |
| `text: ...` (contient) | `title: ...` (contient) |
| `value: ...` (champ, exact) | `console: regex` (un message console apparaît) |
| `count: 0` | `no_console: regex` (aucun message depuis le début de la feature) |
| `enabled: true/false` | `js: "expression"` (devient vraie ; une fonction `async` est attendue) |
| `checked: true/false` (case, radio) | |
| `number: 45` (+ `tolerance: 0.01`) : la valeur du champ, ou le texte, lu comme un nombre | |
| `rendered: true/false` : l'élément dessine autre chose qu'une couleur unie (au moins 0,5 % des pixels diffèrent du fond) ; fait pour les canvas du jeu | |
| `animated: true/false` : deux captures à 500 ms d'écart diffèrent (au moins 0,05 % des pixels) : un objet qu'un script fait tourner | |
| `dominant_color: "#3366CC"` (+ `color_tolerance`, défaut 12 par canal) : la couleur la plus fréquente de l'élément, par exemple le fond du jeu | |

Exemple : le solde a pris 500 pièces après le paiement.

```yaml
- store: coins_before
  js: "() => fetch('${base.api}/users/me', { credentials: 'include' }).then(r => r.json()).then(u => u.money ?? 0)"
# ... paiement ...
- expect:
    js: "async () => ((await (await fetch('${base.api}/users/me', { credentials: 'include' })).json()).money ?? 0) >= ${var.coins_before} + 500"
    timeout: 30s
```

`locale: fr-FR` en tête de suite fixe la langue du navigateur : le launcher et Stripe suivent
cette langue, donc leurs textes (« Débloquer pour 10 pièces », « Carte bancaire ») ne changent
pas selon la machine.

### Variables

`${env.NOM}` (environnement ou `.env`, masqué dans tous les rapports), `${base.nom}`
(`base_urls`), `${var.nom}` (`vars` ou `store`), `${run.id}` (unique par run : nommer ce qu'on
crée `e2e-${run.id}` permet de le retrouver et de le supprimer).

Piège YAML : dans `{ ... }`, une valeur contenant `${...}` doit être entre guillemets :
`{ name: "e2e-${run.id}" }`.

## Ce que les scénarios livrés ont appris de la prod (novembre 2026)

- **WebGPU obligatoire.** Le build wasm de l'éditeur (Bevy 0.18, feature `webgpu`) n'a pas de
  repli WebGL2 : sans adaptateur WebGPU, Bevy panique dès l'init du renderer
  (`bevy_render/src/renderer/mod.rs:281`) et le viewport reste noir.
- **Headless = 3D instable.** Avec `--headless`, Chromium expose un WebGPU logiciel
  (SwiftShader) ; Bevy démarre puis panique (`wgpu ... createBuffer failed ... mappedAtCreation`).
  Les features 3D se lancent donc en mode visible, sur une machine avec GPU. Le smoke, lui,
  tourne en headless.
- **Pas de protection anti-bot.** Le front est servi par Caddy, sans challenge Cloudflare :
  un navigateur automatisé passe sans règle d'exception.
- **Import dédupliqué.** L'éditeur hache le fichier et demande `/catalog/<projet>/lookup` ;
  `/convert` n'est appelé que pour un fichier jamais vu. Le scénario attend donc le lookup.
- **Paiement.** Stripe est en clé de test en prod (bandeau « Environnement de test » sur
  Checkout, que le scénario vérifie avant de payer). Le formulaire est dans une iframe Stripe
  Elements ; le webhook crédite les pièces avant même le retour sur `/shop`, et l'app retire
  `?success=true` de l'URL aussitôt.
- **Le jeu n'affiche rien sans caméra reculée.** Une caméra ajoutée est à l'origine, dans les
  objets : le jeu montre un fond uni. Le scénario la place en (0, 1, 6).
- **Hiérarchie.** Un clic sur une ligne déjà sélectionnée la désélectionne (d'où `select`), et
  l'Inspector a lui aussi le rôle `tree` : la hiérarchie se cible par `[data-slot=hierarchy-view]`.
- **Launcher en français**, éditeur en anglais : d'où `locale: fr-FR`. Le launcher a aussi sa
  propre connexion, même si le cookie de l'API est partagé.
- **Pièces de test.** Chaque run crédite 500 pièces de test et en dépense 10 ; le jeu acheté reste
  dans « Jeux achetés » du compte de test après sa dépublication.

## Développement

```sh
pytest                 # 70 tests, dont 6 qui lancent un Chromium headless sur une page locale
python scripts/make_cube_glb.py   # régénère scenarios/fixtures/e2e-cube.glb
```

| Module | Rôle |
| --- | --- |
| `schema.py` | Le format (Pydantic) : une classe par action, validation stricte, JSON Schema |
| `loader.py` | Lecture YAML/JSON, `.env`, variables `${...}`, masquage des secrets |
| `runner.py` | Ordre, dépendances, filtres, cleanup, statuts ; ne connaît pas le navigateur |
| `browser.py` | L'exécuteur Playwright : cibles → locators, actions, vérifications |
| `report.py` | HTML, JSON, JUnit, webhook |
| `cli.py` | `run`, `validate`, `schema` |

Ajouter une action : une classe dans `schema.py` (ajoutée à `STEP_MODELS`) et son cas dans
`PlaywrightExecutor._dispatch`.
