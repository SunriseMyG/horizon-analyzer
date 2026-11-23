# AGENTS.md — horizon-analyzer

Guide pour un agent (ou un dev) qui reprend le projet. À lire avant de toucher au code ou aux
scénarios. Le README et `docs/scenarios.md` s'adressent aux utilisateurs ; ce fichier dit comment
le projet marche de l'intérieur, ce qui a été vérifié en prod et les pièges déjà rencontrés.

## Le projet en bref

horizon-analyzer rejoue **en production** les parcours critiques du moteur de jeu Horizon
(play-horizon.games), décrits dans un fichier YAML, et écrit un rapport feature par feature.
Python 3.11+, Playwright (API sync, Chromium), Pydantic, Typer.

- `scenarios/smoke.yaml` : 3 features, ~2 s, n'écrit rien. Headless, CI toutes les heures.
- `scenarios/critical.yaml` : 17 features, du créateur au joueur. Il crée un projet, importe
  un `.glb`, le transforme, ajoute une lumière, une caméra et des primitives, lance le jeu dans
  l'éditeur, le publie, achète des pièces par Stripe (mode test) et lance le jeu depuis le
  launcher. **Navigateur visible et vrai GPU obligatoires** (WebGPU).
- `scenarios/engine.yaml` : 18 features, ~2 min. Il teste le moteur. Il importe l'ange
  « cemetery_angel » (prefab glTF texturé, 35 Mo), ajoute un sol, un cube et une sphère dorés
  (reflets), une lumière avec ombres et une caméra au fond bleu. Il construit ensuite un script
  dans l'éditeur de nœuds (On Every Frame → Rotate Y 2°) et l'attache à l'ange et au cube. Il fait
  aussi écrire un second script par l'assistant IA (un prompt qui fait flotter la sphère) et
  l'attache à la sphère. Il contient deux cas qui ne fonctionnent pas dans Horizon : un .glb
  corrompu et une texture ordinaire en skybox. Ils sont écrits comme des features normales et
  sortent **KO exprès** : un run normal donne 16 OK, 2 KO et un code de sortie 1. Leur
  `teardown` remet l'éditeur en ordre, puis la scène continue avec une couleur de fond. Enfin, il lance
  le jeu : la couleur dominante doit être le bleu choisi, et l'image doit bouger. Il ne publie et
  ne paie rien. GPU obligatoire.
- `scenarios/atp.yaml` : les 78 features du document d'ATP (atp_770_Horizon), F1 à F78 avec
  les numéros du document (F77 et F78 jouées après F66). Inscription avec code lu par l'API de mail.tm
  (compte et boîte supprimés en cleanup ; yopmail est exclu : Cloudflare refuse les navigateurs
  pilotés), tout l'éditeur, chaque champ des composants, publication,
  launcher, Stripe. Écrit d'après le code source (clone du 2026-11-07), **pas encore lancé en
  prod** : les sélecteurs repris de critical/engine sont sûrs, les autres sont à confirmer au
  premier run. Besoin de `HORIZON_SIGNUP_PASSWORD` dans `.env`. Fichiers :
  `scripts/make_atp_fixtures.py`.

Le code source d'Horizon est dans un autre dépôt (monorepo alpha) :
`C:\Users\steve\Documents\Epitech\eip\horizon`. C'est lui qui tourne en prod, pas `horizon-new`.
Le service d'authentification est dans `services/auth_service`.

## Commandes

```powershell
python -m venv .venv; .venv\Scripts\pip install -e ".[dev]"; .venv\Scripts\playwright install chromium
copy .env.example .env                                   # HORIZON_EMAIL, HORIZON_PASSWORD (compte de test)

.venv\Scripts\python -m pytest -q                        # 74 tests ; ceux marqués `browser` lancent Chromium headless, sans réseau
.venv\Scripts\horizon-analyzer validate scenarios\critical.yaml
.venv\Scripts\horizon-analyzer schema -o scenarios\horizon-analyzer.schema.json   # à refaire après tout changement de schema.py
.venv\Scripts\horizon-analyzer run scenarios\critical.yaml [--no-trace] [--only <id>] [--tags x] [--slow-mo 300] [--no-cache]
.\run-all.ps1                                            # smoke headless puis critical visible ; installe le venv si absent
.venv\Scripts\python scripts\check_leftovers.py          # restes e2e-* sur le compte de test (lecture seule)
```

Un run critique prend environ 1 à 3 min selon le réseau. Il ouvre une fenêtre Chromium sur la
machine et **écrit en prod** : il crée un projet, publie un jeu, fait un paiement Stripe de
test (+500 pièces) et achète le jeu (−10). Tout est nettoyé à la fin (voir « Nettoyage »).
Ne lance jamais deux runs en même temps : ils partagent le même compte.

## Architecture (`src/horizon_analyzer/`)

| Fichier | Rôle |
| --- | --- |
| `schema.py` | Le DSL en Pydantic (`extra=forbid`). `Target` (une seule base parmi role/label/text/testid/css/id… + `within`, `has`, `has_text`, `nth`, `frame`). Un modèle par action (`goto`, `click`, `select`, `hover`, `fill`, `press`, `upload`, `drag`, `choose`, `wait`, `reload`, `screenshot`, `store`, `expect`). `drag` accepte `to_position` ou `to_offset` (depuis le centre de `to`), `from_offset` (depuis le centre de `drag`), `steps` (glissé en N petits mouvements : obligatoire dans l'éditeur de nœuds et le viewport, qui ignorent le saut unique de `drag_to`) et `button` (`right`, `middle`, avec `steps`). `press` accepte `hold` (touche tenue : Bevy lit les touches enfoncées à chaque image). `Expectation` : visible, text, value, number(+tolerance), count, enabled, checked, rendered, animated, dominant_color(+color_tolerance), url, title, console, no_console, js. `Feature` (depends_on, mutating, requires_webgpu, cleanup), `Suite`. |
| `loader.py` | Chargement YAML/JSON, `.env` (n'écrase pas l'environnement), `Context.render()` pour `${env.X}`, `${var.x}`, `${run.id}`, `${base.x}`. Les valeurs venant de `env` sont masquées (`***`) dans tous les rapports. |
| `runner.py` | Orchestration, indépendante du navigateur (protocole `Executor`). Le `teardown` d'une feature est joué juste après elle, qu'elle passe ou non ; un échec n'y fait échouer qu'une feature qui passait. Statuts passed/failed/blocked/skipped. Une feature est sautée si une dépendance n'a pas passé, et bloquée si elle demande WebGPU sans adaptateur. Les cleanups sont enregistrés au début et joués en LIFO à la fin, même après un échec. `fail_on_console` fait échouer une feature qui passait. |
| `browser.py` | `PlaywrightExecutor` : **une seule page** pour tout le run (la connexion de F1 sert à la suite). Voir « Mécanismes de robustesse ». |
| `report.py` | `report.html` (français, mode sombre), `report.json`, `junit.xml`, webhook Discord/Slack. |
| `cli.py` | Typer : `run`, `validate`, `schema`. Force la sortie en UTF-8. |

Tests : `tests/test_browser.py` sert une page locale (iframe srcdoc, canvas, listbox, menu
contextuel, lien `target=_blank`, mini serveur HTTP pour le cache). `test_runner.py` utilise un
`FakeExecutor`. Un comportement nouveau de l'executor = un test dans `test_browser.py`.

### Mécanismes de robustesse (browser.py), et pourquoi ils existent

- **`rendered`** : on ne lit pas un canvas WebGPU. L'outil prend une capture, retire 3 % de
  bord, puis compte les pixels différents de la couleur dominante. Il en faut au moins 0,5 %
  (`RENDERED_MIN_FRACTION`).
- **Repère de console** : `expect: console` regarde les messages depuis la dernière navigation
  du cadre principal (`framenavigated`), pas depuis le début de la feature. Bevy peut loguer son
  adaptateur pendant la feature précédente.
- **`keep_window_open()`** : une fenêtre réduite passe de ~165 à ~2 images/s alors que la page
  se dit toujours « visible ». Bevy est alors quasi gelé. L'outil restaure la fenêtre par CDP
  avant chaque étape et dans les boucles d'attente. Une fenêtre masquée ou hors écran ne pose
  pas de problème.
- **`close_stray_tabs()`** : un onglet ouvert par le site (lien `target=_blank`, par exemple le
  pied de page Stripe) est refermé, et la page du test revient au premier plan. C'est noté dans
  le rapport.
- **`AssetCache`** : tout ce qui est sous `/_app/immutable/` (code SvelteKit et wasm Bevy, avec
  un hash dans le nom) est servi depuis `runs/.cache/` après le premier téléchargement. Les
  fichiers inutilisés depuis 14 jours sont purgés. Le wasm de l'éditeur pèse 39 Mo décompressé
  (9 Mo compressé). `route.fetch(timeout=0)` est volontaire : à 30 s, le gros fichier n'était
  jamais mis en cache sur une connexion lente.
- **`_capture()`** : toutes les captures d'un élément (`rendered`, `animated`, `dominant_color`,
  `screenshot: of:`) sont **découpées dans une capture de la fenêtre entière**. N'utilise jamais
  `locator.screenshot()` en mode visible : Chromium fait alors clignoter la fenêtre pendant une
  ou deux images. On ne voit plus que l'élément, en haut à gauche, sur fond gris foncé. Ce
  glitch a été vu dans une vidéo d'un run de l'utilisateur, puis reproduit en capturant l'écran
  Windows : 2 images glitchées sur 129 avec `locator.screenshot()`, 0 sur 156 avec `_capture()`.
  Le screencast CDP et une sonde `requestAnimationFrame` ne le détectent pas (il se produit dans
  la fenêtre, pas dans la page).
- **`animated`** compare deux captures à 500 ms d'écart (part de pixels dont la luminance change de plus de 24/255, seuil 0,05 %). Une scène WebGPU immobile se redessine à l'identique (0 %). **`dominant_color`** prend la couleur la plus fréquente de la capture, par exemple le `clear_color` de la caméra.
- **`select`** ne clique que si `aria-selected != true`, parce que cliquer une ligne déjà
  sélectionnée de la hiérarchie la désélectionne.

## Écrire ou modifier un scénario

- La référence du format pour l'équipe est `docs/ecrire-un-scenario.md` : chaque champ, chaque
  action et ses options, les cibles, les vérifications, les pièges YAML, et un exemple complet.
  **Tout changement de `schema.py`** (nouvelle action, option, vérification) s'y reporte, avec le
  résumé du README et le JSON Schema régénéré. L'exemple de la section 9 doit rester valide
  (`horizon-analyzer validate`).
- Chaque feature est précédée d'un bloc de commentaire en français : `Teste` / `Vérifie` /
  `Écrit` / `Pourquoi` / `Capture`. Garde ce format, l'utilisateur y tient.
- Clés YAML piégeuses : une valeur avec `${...}` dans une map `{ }` doit être entre guillemets.
  Pour `press`, la cible est `target:`, pas `on:` (YAML lit `on` comme un booléen).
- Les ancres (`&hierarchy`, `&position_x`, `&rotation_y`, `&scale_x`, `&stop`, `&stripe`,
  `&game_dialog`, `&search`…) sont réutilisées plus bas. Vérifie leurs usages avant de les
  changer.
- Une feature qui écrit en prod a `mutating: true` (`--safe-only` l'exclut). Si elle crée
  quelque chose, ajoute un `cleanup:`.
- Une dépendance (`depends_on`) doit être déclarée plus haut dans le fichier.
- Après modification : `validate`, `pytest`, puis un run réel (`--only <id>` suffit souvent).

### Préférences de l'utilisateur (à respecter)

- **Un cas qu'Horizon ne gère pas sort KO, pas OK.** On écrit le comportement attendu (« ça doit
  marcher ») ; si Horizon échoue, la feature est KO, avec la cause dans le rapport. Pas de feature
  qui vérifie qu'une erreur se produit. Mettre un `teardown` pour que la suite du scénario
  continue.

- **Aucun rechargement de page dans l'éditeur.** Tout le parcours reste sur la même scène.
  Un refresh voulu ressemble à un bug pour qui regarde le test : la feature
  EDITOR-scene-persisted a été supprimée pour cette raison. Ne réintroduis pas de `reload`.
- **Le test doit se regarder** : des pauses de 2 à 3 s laissent voir la scène chargée, le
  modèle posé, la scène complète et le jeu lancé. Garde-les.
- **Interface en français** pour les rapports, les messages de la CLI, les commentaires YAML et
  la doc. Le code et les identifiants restent en anglais.
- Pas de commit tant que l'utilisateur ne le demande pas. Rien n'est encore commité.

## Ce qui a été vérifié en prod

- **Domaines** : `editor.play-horizon.games`, `play.play-horizon.games` (launcher),
  `api.play-horizon.games`, avec un tiret. `playhorizon.games` est un domaine parqué.
  Auto-hébergé derrière Caddy, sans Cloudflare.
- **Auth** : cookie JWT httpOnly. L'éditeur et le launcher ont chacun leur formulaire de
  connexion. La gateway limite `/login` à 60 requêtes/min par IP et répond 429 au-delà. Un 401
  « Invalid email or password » avec des identifiants valides a été vu une fois : un raté
  passager du backend.
- **Moteur** : Bevy 0.18 en wasm, backend WebGPU uniquement, **sans repli WebGL2** : sans
  WebGPU, il plante dans `bevy_render renderer/mod.rs`. En headless, Chromium fournit
  SwiftShader et Bevy plante (createBuffer). D'où `fail_on_console: "panicked at"` et la
  suite critique en mode visible.
- **Canvas** : `#scene-view-canvas` (viewport de l'éditeur), `#game-view-canvas` (onglet Game),
  `#game-canvas` (launcher, `/play/<id>`). Bevy logue `backend: BrowserWebGpu` au démarrage.
- **Éditeur** :
  - Hiérarchie `[data-slot=hierarchy-view]`. L'Inspector est aussi un `role=tree`, d'où les
    `within`.
  - Le clic droit ouvre « Create Object » (Empty, Cube, Sphere, Camera, Point Light,
    Directional Light). Sur une ligne, on a Duplicate et Delete.
  - Transform : spinbuttons X/Y/Z sous les spans `position`, `rotation`, `scale`. La rotation
    passe par un quaternion et revient en 45.000004, d'où `number` + `tolerance`.
  - Bouton Play : aria-label « Play », texte « Start ». Une fois arrêtés, les boutons restent
    dans le DOM, dans `div.pointer-events-none`.
  - La caméra doit être placée en (0, 1, 6) pour que le jeu montre le cube.
- **Import** : dédupliqué par hash. `/catalog/<projet>/lookup` est toujours appelé, `/convert`
  seulement pour un nouveau fichier. L'asset prend le nom du **mesh** (`e2e-cube`, généré par
  `scripts/make_cube_glb.py`). Le glisser-déposer ne fonctionne que depuis l'onglet « My
  Assets » (`#tab-mine`).
- **Launcher** : interface en français (locale `fr-FR`), plus récent que le clone local. On y
  trouve « Débloquer pour 10 pièces », « Jouer », « Quitter ». Le solde se lit via
  `fetch(api/users/me).money`.
- **Stripe** : la prod utilise une clé `sk_test`, et Checkout affiche « Environnement de
  test ». Le scénario refuse de payer sans ce bandeau.
  - Le formulaire est dans `iframe[src*='js.stripe.com/v3/elements-inner']:visible`.
  - On valide avec **Entrée dans le champ du nom**, pas en cliquant « Payer ». La page bouge
    en se mettant en place, et un clic au mauvais moment ouvrait `stripe.com/fr/legal/consumer`.
  - L'app retire `?success=true` de `/shop`.
  - Carte de test : 4242 4242 4242 4242, 12/34, CVC 123.
- **Scripts no-code** (onglet Scripting, xyflow) :
  - Un script neuf contient déjà `on_every_frame_node`.
  - « Add node » ouvre la bibliothèque (champ « Search nodes... »). Les cartes sont des `[role=button]` avec leur description (« Rotate the object… », « A literal value. »). Un clic ajoute le nœud au centre, donc les nœuds s'empilent : il faut les écarter en tirant `.dragHandle` avec `steps`.
  - Les poignées ont un `[data-handleid]` : `on_every_frame_node_source_1`, `rotate_node_target_1` (flux), `rotate_node_target_2..4` (x, y, z), `value_node_source_1`.
  - Le type du nœud Value est un `<select>` natif (`choose`). La valeur se saisit dans le champ « Enter a float ».
  - « Save » envoie le graphe à compile-service, qui le compile en wasm, puis affiche le toast « Script saved ».
  - Pour attacher un script : Inspector > « Add Component » (groupe `#add-component-list`) > « Script », puis glisser `[id^=script-card-]` (Assets > `#tab-script`) sur « Drop Script here ».
- **Inspector** :
  - Les champs numériques sont des spinbuttons nommés d'après le champ (`roughness`, `fov`, `illuminance`…).
  - Les couleurs sont des color pickers Ark UI (`[data-scope=color-picker][data-part=root]`). On saisit le texte dans `input[data-part=channel-input][type=text]:visible` puis on fait Entrée.
  - Les booléens sont des switches avec une case cachée (`shadows_enabled`, cochée par défaut sur une lumière directionnelle).
  - Il n'y a pas de champ `metallic` : les reflets passent par une `roughness` basse. Ils se voient sur une sphère, pas sur les faces plates d'un cube.
  - Le `clear_color` de la caméra ne s'applique qu'en jeu, pas dans le viewport de l'éditeur.
- **Assistant IA** (panneau « AI Assistant » de l'onglet Scripting) :
  - Il reçoit le graphe courant et le prompt (zone de texte « Ask the AI to explain or write your script… », bouton « Send »), puis appelle `POST /ai/chat` en streaming.
  - Le graphe qu'il propose est validé par le vérificateur de types de l'éditeur. En cas d'erreur, l'IA corrige elle-même, jusqu'à 5 fois. Le graphe validé est ensuite chargé, avec le message « Updated the script ».
  - Si les erreurs persistent, le message contient « This script contains errors ».
  - Il répond en 15 à 60 s.
  - Sans consigne précise, il fait bouger un objet avec Translate (déplacement relatif par image). Pour un mouvement borné, demander Set Position.
  - « New » demande confirmation (« Continue ») dès qu'un script a été enregistré.
- **Cas d'erreur vérifiés** :
  - Un .glb illisible : `POST /convert` répond 400, et le dialogue d'import affiche une alerte (`role=alert`) « Import failed » avec « invalid input: conversion failed: glTF error… ». Le dialogue reste ouvert : le fermer avec « Cancel ».
  - Une texture ordinaire en skybox : le jeu (`horizon-studio/game`, `prepare_skyboxes`) attend une bande verticale de 6 faces et appelle `reinterpret_stacked_2d_as_array(6)`. Avec une image normale, WebGPU logue en boucle « Dimension (TextureViewDimension::e2D) … doesn't match the expected dimension (TextureViewDimension::Cube) » (en warning, pas en erreur), et le jeu est entièrement noir. Après « Clear Texture », le jeu suivant se lance normalement, sans recharger la page.
- **L'ange** s'importe comme un prefab « cemetery_angel_-_miller » (racine avec un Transform seul, rotation X −90°, échelle 1,0471, environ 2 m de haut), plus 16 meshes « angel.001_0 » et une texture. Déjà dans le catalogue du compte, il est retrouvé par son hash en 1 s, sans renvoyer les 35 Mo.
- **Gels de 200 à 300 ms** dans l'éditeur (sélection, clic droit, Play) : ils sont identiques
  avec ou sans trace, donc côté app.

### Lu dans le code source pour atp.yaml (à confirmer en prod)

Constaté au premier run d'atp.yaml (2026-11-21) :

- Les boutons « Game settings » et « History » de la barre d'outils sont des `<div>` (déclencheurs
  Ark), pas des `button` : `{ css: "[data-scope=dialog][data-part=trigger]", has_text: Game settings }`
  et `[data-scope=popover][data-part=trigger]` pour History.
- « Save » d'un script refuse un graphe sans nœud relié au départ (« every trigger node is
  empty ») et ouvre une alerte « Save failed » qui bloque toute la page : prévoir un `teardown`
  avec `press: Escape`.
- Un `.wasm` importé n'apparaît pas dans les assets (la liste vient de compile-service).
- api.mail.tm n'envoie pas d'en-tête CORS : l'appeler depuis sa propre origine.
- Clic droit maintenu dans le viewport : Chrome refuse le verrouillage du pointeur si la fenêtre
  du test n'a pas le focus (« not valid for pointer lock ») ; bruit sans conséquence.

- Caméra de l'éditeur (`scene/src/scene_camera.rs`) : départ en (10, 10, 10) vers l'origine ;
  touches KeyW/A/S/D, Espace/Maj ; clic droit = regarder, clic milieu = déplacer. Position
  gardée par projet dans `localStorage['camera-per-room']`. Touche F (hors champ texte) :
  recentrer sur la sélection, sans changer l'orientation.
- Gizmo (`transform-gizmo` 0.9) : 75 px ; translation = cercle central (vue), rotation =
  arcball au centre, échelle = poignées d'axe seulement. Un glissé hors gizmo en mode Select
  trace un rectangle de sélection.
- Hiérarchie : `role=treeitem` avec `aria-level`, `aria-expanded` sur une branche (repliée par
  défaut), bouton `[data-part=trigger]` pour déplier. Le menu propose aussi « Create Child »,
  « Empty », « Sphere », « Point Light ».
- Inspector : interrupteurs `[data-slot=switch]` ; collider = `<select>` ; touches du
  CharacterController = un bouton qui ouvre un petit clavier (flèches ↑ ↓ ← →) ; Mesh, Texture et
  Script se déposent sur « Drop … here » (un mesh depuis Assets > Meshes, pas My Assets).
- Game settings (bouton « Game settings ») : curseur « Ambient light » (0-1000, défaut 500),
  « Loading image », interrupteur « Performance Indicator ». Thème : radios « Light mode » /
  « Dark mode ». Historique : bouton « History », lignes « v<seq+1> » avec « Restore ».
- Éditeur de nœuds : supprimer = Retour arrière ou le bouton `title=Delete` des contrôles ;
  clic milieu = déplacer la vue ; panneaux « Variables » et « Components » (zag floating-panel).
- Inscription : mot de passe de 8 caractères minimum (majuscule, minuscule, chiffre, spécial) ;
  code à 6 chiffres par e-mail (« Your Horizon verification code ») ; DELETE /users/<id>.

## Nettoyage et données de test

- Tout ce que le run crée s'appelle `e2e-<run id>` (ex. `e2e-20261119-1959-7d14`).
- En fin de run, `F15-publish` dépublie le jeu, puis `F4-create-project` supprime le projet.
- Un run coupé (réseau, fenêtre fermée) peut laisser des restes. `scripts/check_leftovers.py`
  les liste : supprime-les depuis l'accueil de l'éditeur (Edit > Unpublish Game, puis
  l'icône de suppression).
- Projets légitimes du compte, à ne jamais toucher : « ATP Check » (publié) et « Test ».
- Secrets : uniquement dans `.env` (gitignoré) ou dans les secrets GitHub. Jamais dans un YAML,
  un rapport ou un commit.

## Quand un run échoue

Commence par `runs/<run id>/failures/<feature>.png` et `report.html`. Avec `--trace` (le
défaut), `playwright show-trace runs/<run id>/trace.zip` rejoue tout. Causes déjà rencontrées :

| Symptôme | Cause |
| --- | --- |
| EDITOR-viewport sans « backend: BrowserWebGpu », et toutes les features 3D sautées | Wasm pas arrivé à temps (connexion lente). Relancer : le cache se remplit au premier run |
| Timeout sur `Locator.screenshot` ou sur un `fill`, alors que la page est affichée | Machine saturée (peu de RAM libre) ou fenêtre réduite |
| `ERR_INTERNET_DISCONNECTED` | Réseau de la machine coupé |
| `strict mode violation` | Le sélecteur trouve deux éléments : préciser la cible (`within`, `nth`, `exact`) |
| `panicked at` | Bevy a planté : headless, ou un vrai bug du moteur |

Ne corrige pas un échec en allongeant les délais à l'aveugle. Regarde la capture : un
viewport encore blanc veut dire que le wasm n'est pas chargé, la grille visible veut dire que
Bevy tourne.

## État au 2026-11-20 et pistes

- `critical.yaml` : dernier run complet à 17/17, `20261119-1959-7d14`. Les runs suivants ont
  surtout échoué à cause de la machine (connexion vers 190 Ko/s, 1,5 Go de RAM libre), pas
  d'Horizon.
- `engine.yaml` : 16 OK + les 2 KO attendus (modèle corrompu, texture en skybox). L'utilisateur veut que ces cas sortent KO, pas OK : on part du principe que tout doit fonctionner. Ne les retourne pas en « vérifier que ça échoue ».
- À faire :
  - confirmer la stabilité sur une série de 3 runs, sur une bonne connexion et une machine peu
    chargée ;
  - envisager un runner self-hosted avec GPU pour la suite critique en CI (aujourd'hui, seul le
    smoke tourne sur GitHub Actions, voir `.github/workflows/smoke.yml`).
- Le document de R&D initial (questions tranchées, PoC) est une Claude Doc :
  https://claude.ai/artifact/AnYYq2J6UzbCqLoVusf1Tr
