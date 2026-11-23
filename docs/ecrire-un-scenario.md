# Écrire un scénario

Ce guide explique tout ce qu'on peut écrire dans un fichier de scénario : chaque champ, chaque
action, chaque vérification. Pour lancer les scénarios existants et lire leurs rapports, voir
[scenarios.md](scenarios.md).

## Sommaire

1. [Le fichier en un coup d'œil](#1-le-fichier-en-un-coup-dœil)
2. [L'en-tête de la suite](#2-len-tête-de-la-suite)
3. [Les variables `${…}`](#3-les-variables-)
4. [Les features](#4-les-features)
5. [Les étapes (steps)](#5-les-étapes-steps)
6. [Les cibles : désigner un élément](#6-les-cibles--désigner-un-élément)
7. [Les vérifications (`expect`)](#7-les-vérifications-expect)
8. [Durées, pièges YAML, validation](#8-durées-pièges-yaml-validation)
9. [Exemple complet commenté](#9-exemple-complet-commenté)

## 1. Le fichier en un coup d'œil

Un fichier de scénario est un fichier YAML (ou JSON) rangé dans `scenarios/`. Il contient une
**suite**, c'est-à-dire une liste de **features**. Une feature est une fonctionnalité testée,
avec sa liste d'**étapes** :

```yaml
suite: horizon-prod-exemple            # nom de la suite (en-tête)
base_urls:
  editor: https://editor.play-horizon.games

features:                              # la liste des features
  - id: F1-login                       # une feature…
    name: Connexion à l'éditeur
    steps:                             # …et ses étapes, jouées dans l'ordre
      - goto: ${base.editor}/
      - fill: { label: Email }
        value: ${env.HORIZON_EMAIL}
      - fill: { label: Password, exact: true }
        value: ${env.HORIZON_PASSWORD}
      - click: { role: button, name: Sign In }
      - expect: { target: { role: heading, name: Welcome back }, visible: true }
```

Ce qu'il faut savoir avant d'écrire :

- **Tout se passe sur une seule page.** Les features tournent dans l'ordre du fichier, dans le
  même onglet, comme une personne qui enchaîne les actions. La connexion faite par la première
  feature sert donc à toutes les suivantes.
- **Une étape = une action.** Chaque étape commence par le nom de son action (`goto`, `click`,
  `fill`…) et peut avoir des options à côté.
- **Une faute de frappe est refusée avant de lancer le navigateur.** Une clé inconnue, une
  option mal écrite ou une dépendance qui n'existe pas fait échouer
  `horizon-analyzer validate`, avec la feature et l'étape concernées.
- **L'autocomplétion existe.** La première ligne `# yaml-language-server: $schema=./horizon-analyzer.schema.json`
  branche le JSON Schema. Dans VS Code, avec l'extension YAML de Red Hat, on a alors
  l'autocomplétion et le soulignement des erreurs pendant qu'on écrit.

## 2. L'en-tête de la suite

Ces champs se placent au début du fichier, au même niveau que `features`.

| Champ | Obligatoire | Défaut | À quoi il sert |
| --- | --- | --- | --- |
| `suite` | oui | | Nom de la suite, affiché dans le terminal et les rapports. Ex. `horizon-prod-engine` |
| `description` | non | | Une phrase qui dit ce que la suite couvre |
| `base_urls` | non | `{}` | Les adresses du site, réutilisées en `${base.<nom>}`. Ex. `editor: https://editor.play-horizon.games` |
| `vars` | non | `{}` | Des valeurs fixes réutilisées en `${var.<nom>}` (une couleur, un nom…) |
| `locale` | non | langue du système | Langue du navigateur, ex. `fr-FR`. À fixer quand on cherche du texte : le launcher et Stripe changent de langue selon le navigateur |
| `timeout` | non | `15s` | Attente maximale par défaut de chaque étape (voir [Durées](#durées)) |
| `dialogs` | non | `accept` | Réponse aux boîtes `confirm()` ou `alert()` du site : `accept` ou `dismiss` |
| `ignore_console` | non | `[]` | Expressions régulières : les erreurs console qui correspondent n'apparaissent pas dans le rapport (bruit connu) |
| `fail_on_console` | non | `[]` | Expressions régulières : une feature dont toutes les étapes ont passé devient KO si une erreur console correspond pendant qu'elle tourne. Ex. `"panicked at"`, le plantage du moteur Bevy |
| `features` | oui | | La liste des features (au moins une) |

```yaml
suite: horizon-prod-engine
description: Scripts, lumière, ombres et fond, vérifiés en jeu.
base_urls:
  editor: https://editor.play-horizon.games
  api: https://api.play-horizon.games
locale: fr-FR
timeout: 15s
dialogs: accept
ignore_console:
  - "GPU stall due to ReadPixels"
fail_on_console:
  - "panicked at"
  - "^\\[pageerror\\]"
vars:
  sky: "#3366CC"
```

## 3. Les variables `${…}`

Partout où on écrit du texte (une URL, une valeur à saisir, un nom à chercher), on peut insérer
une variable. Elle est remplacée au moment où l'étape s'exécute.

| Variable | Valeur |
| --- | --- |
| `${env.NOM}` | Une variable d'environnement, en général lue dans `.env`. Sert aux identifiants : `${env.HORIZON_EMAIL}`, `${env.HORIZON_PASSWORD}`. Ces valeurs sont **remplacées par `***`** dans les rapports |
| `${base.nom}` | Une adresse de `base_urls`. Ex. `${base.editor}/` |
| `${var.nom}` | Une valeur de `vars`, ou une valeur enregistrée plus tôt par une étape `store` |
| `${run.id}` | L'identifiant unique du run, ex. `20261120-1111-5e04`. Sert à donner un nom unique à ce qu'on crée : `e2e-${run.id}` |

Une variable inconnue ou absente de `.env` fait échouer l'étape, avec un message qui dit
laquelle manque.

**Ne jamais écrire un mot de passe en clair dans un scénario** : toujours `${env.…}`. Attention
aussi au fichier `trace.zip` d'un run : il contient tout ce qui a été tapé, mot de passe compris.
Ne pas le partager.

## 4. Les features

Une feature regroupe les étapes qui testent une fonctionnalité.

| Champ | Obligatoire | Défaut | À quoi il sert |
| --- | --- | --- | --- |
| `id` | oui | | Identifiant unique, sans espace (lettres, chiffres, `-`, `_`, `.`). Il sert pour `--only` et `depends_on`. Convention : celui du beta test plan (`F5-import-mesh`) ou un préfixe de domaine (`EDITOR-…`, `ENGINE-…`, `LAUNCHER-…`) |
| `name` | oui | | Libellé lisible, en français, affiché dans le terminal et le rapport |
| `tags` | non | `[]` | Étiquettes pour lancer un sous-ensemble avec `--tags`. Ex. `[engine, 3d, script]` |
| `depends_on` | non | `[]` | Les features qui doivent avoir **passé** pour que celle-ci tourne. Elles doivent être **déclarées plus haut** dans le fichier. Si l'une a échoué ou a été sautée, celle-ci est **sautée** (SKIP) au lieu d'échouer en cascade |
| `mutating` | non | `false` | `true` si la feature **écrit en prod** (crée un projet, publie, paie…). `--safe-only` exclut ces features |
| `requires_webgpu` | non | `false` | `true` si la feature a besoin du moteur 3D. Sans WebGPU dans le navigateur, elle est marquée **bloquée** (BLOC) plutôt qu'en échec : ce n'est pas un bug d'Horizon |
| `steps` | oui | | Les étapes, jouées dans l'ordre. La première qui échoue arrête la feature |
| `teardown` | non | `[]` | Des étapes jouées **juste après** la feature, **qu'elle passe ou échoue**. Elles remettent la page en ordre pour la suite : fermer un dialogue resté ouvert, arrêter le jeu, retirer une texture. Si une étape de teardown échoue, une feature qui avait passé devient KO |
| `cleanup` | non | `[]` | Des étapes qui **défont ce que la feature a créé en prod** : supprimer le projet, dépublier le jeu. Elles tournent **à la fin du run**, de la dernière feature à la première, même après un échec |

**`teardown` ou `cleanup` ?**
- `teardown` sert à **remettre l'écran en état**, tout de suite, pour la feature suivante.
- `cleanup` sert à **effacer les traces en prod**, une fois tout le reste terminé.

**Les statuts d'une feature dans le rapport**

| Statut | Signification |
| --- | --- |
| OK | Toutes les étapes ont passé, sans erreur console fatale |
| FAIL (KO) | Une étape n'a pas fait ce qui était attendu ; le rapport donne l'étape, la raison et une capture |
| SKIP | Une feature de `depends_on` n'a pas passé |
| BLOC | `requires_webgpu` et pas de WebGPU dans le navigateur |

**Règle de la maison** : une feature décrit ce qui **doit** marcher. Si Horizon ne gère pas un
cas (un modèle corrompu, une texture en skybox), la feature sort KO, avec la cause dans le
rapport. On n'écrit pas de feature qui vérifie qu'une erreur se produit.

```yaml
  - id: F4-create-project
    name: Créer un projet de jeu
    tags: [critical, editor]
    mutating: true                     # crée un projet en prod…
    depends_on: [F1-login]             # …une fois connecté
    steps:
      - click: { role: button, name: Create New Game, nth: first }
      - fill: { id: modal-game-name }
        value: e2e-${run.id}
      - click: { role: button, name: Create Game }
      - expect: { url: "**/editor?id=*", timeout: 20s }
    cleanup:                           # …et le supprime à la fin du run
      - goto: ${base.editor}/
      - hover: { role: heading, name: "e2e-${run.id}", exact: true }
      - click: { title: Delete Project, within: { css: div.group, has: { role: heading, name: "e2e-${run.id}", exact: true }, nth: first } }
```

## 5. Les étapes (steps)

Une étape commence par le nom de l'action, suivi de deux points et de sa valeur. Les options se
placent sur les lignes suivantes, alignées sous le nom de l'action :

```yaml
      - click: { role: button, name: Import model }      # l'action et sa cible
        expect_response: { url: "**/convert", status: 2xx } # une option
        timeout: 30s                                          # une autre option
```

La plupart des actions prennent une **cible** (voir [section 6](#6-les-cibles--désigner-un-élément)).
Toutes attendent que l'élément soit visible et utilisable, jusqu'au `timeout`, avant d'agir.

Récapitulatif :

| Action | Ce qu'elle fait |
| --- | --- |
| [`goto`](#goto--ouvrir-une-adresse) | Ouvre une adresse |
| [`click`](#click--cliquer) | Clique sur un élément (clic gauche, droit, à une position précise) |
| [`select`](#select--sélectionner-sans-désélectionner) | Sélectionne une ligne seulement si elle ne l'est pas déjà |
| [`hover`](#hover--survoler) | Passe la souris sur un élément |
| [`fill`](#fill--remplir-un-champ) | Remplace le contenu d'un champ |
| [`press`](#press--appuyer-sur-une-touche) | Appuie sur une touche ou une combinaison |
| [`upload`](#upload--envoyer-un-fichier) | Met un ou plusieurs fichiers dans un champ « choisir un fichier » |
| [`drag`](#drag--glisser-déposer) | Glisse un élément sur un autre |
| [`choose`](#choose--choisir-dans-une-liste-déroulante) | Choisit une option d'une liste déroulante |
| [`wait`](#wait--attendre) | Attend une durée fixe |
| [`reload`](#reload--recharger-la-page) | Recharge la page |
| [`screenshot`](#screenshot--capture-décran) | Enregistre une capture dans le rapport |
| [`store`](#store--mémoriser-une-valeur) | Mémorise une valeur pour la réutiliser en `${var.…}` |
| [`expect`](#7-les-vérifications-expect) | Vérifie quelque chose (section 7) |

### `goto` : ouvrir une adresse

| Option | Défaut | Rôle |
| --- | --- | --- |
| `expect_response` | | Exige que le chargement déclenche une réponse réseau (voir [`expect_response`](#expect_response--exiger-une-réponse-réseau)) |

```yaml
      - goto: ${base.editor}/
      - goto: ${base.launcher}/shop
```

L'étape attend la fin du chargement de la page.

### `click` : cliquer

| Option | Défaut | Rôle |
| --- | --- | --- |
| `button` | `left` | `left`, `right` (ouvre un menu contextuel) ou `middle` |
| `position` | centre | `{ x, y }` en pixels depuis le coin haut-gauche de l'élément. Sert à cliquer dans une zone vide d'un panneau |
| `force` | `false` | Clique sans attendre que l'élément soit cliquable. À réserver aux éléments que la page désactive volontairement (ex. le bouton Stop du jeu une fois arrêté) |
| `expect_response` | | Exige que le clic déclenche une réponse réseau |
| `timeout` | celui de la suite | Attente maximale |

```yaml
      - click: { role: button, name: Sign In }
        expect_response: { url: "**/login", method: POST, status: 2xx }
      # Clic droit dans la hiérarchie, sous les objets : ouvre le menu « Create Object »
      - click: { css: "[data-slot=hierarchy-view]" }
        button: right
        position: { x: 100, y: 300 }
      - click: { role: menuitem, name: Cube, exact: true }
```

### `select` : sélectionner sans désélectionner

Clique sur l'élément **seulement s'il n'est pas déjà sélectionné** (`aria-selected`), puis
vérifie qu'il l'est. Dans la hiérarchie de l'éditeur, cliquer une ligne déjà sélectionnée la
désélectionne : un `click` ferait alors l'inverse de ce qu'on veut.

| Option | Défaut | Rôle |
| --- | --- | --- |
| `timeout` | celui de la suite | Attente maximale |

```yaml
      - select: { role: treeitem, within: { css: "[data-slot=hierarchy-view]" }, has_text: Camera }
```

### `hover` : survoler

Passe la souris sur l'élément, pour faire apparaître un bouton qui n'est visible qu'au survol.

| Option | Défaut | Rôle |
| --- | --- | --- |
| `timeout` | celui de la suite | Attente maximale |

```yaml
      - hover: { role: heading, name: "e2e-${run.id}", exact: true }
```

### `fill` : remplir un champ

Vide le champ puis y écrit `value`. Fonctionne sur les champs texte, nombre, mot de passe,
zones de texte.

| Option | Défaut | Rôle |
| --- | --- | --- |
| `value` | **obligatoire** | Le texte à saisir. Toujours entre guillemets pour un nombre (`"5"`) |
| `timeout` | celui de la suite | Attente maximale |

```yaml
      - fill: { label: Email }
        value: ${env.HORIZON_EMAIL}
      - fill: { role: spinbutton, name: roughness }
        value: "0.1"
```

Beaucoup de champs de l'Inspector ne prennent la valeur qu'après **Entrée** : ajouter un
`press: Enter` juste après.

### `press` : appuyer sur une touche

| Option | Défaut | Rôle |
| --- | --- | --- |
| `target` | l'élément qui a le focus | L'élément sur lequel appuyer |
| `hold` | | Garde la touche enfoncée pendant cette durée (`1s`, `500ms`), puis la relâche. **Obligatoire pour le moteur 3D**, qui lit à chaque image les touches tenues : une touche enfoncée puis relâchée aussitôt ne déplace pas la caméra |

La valeur est le nom d'une touche, ou une combinaison : `Enter`, `Escape`, `Tab`, `Delete`,
`ArrowDown`, `Control+Z`, `Shift+A`… Pour une touche lue par sa position physique (le moteur
Bevy), donner son code : `KeyW` est la touche Z d'un clavier AZERTY.

```yaml
      - press: Enter
        target: { role: spinbutton, name: X }
      - press: Escape                  # ferme un dialogue ouvert
      - press: KeyW                    # avancer dans la scène (Z en AZERTY)
        hold: 1s
```

L'option s'appelle `target` et pas `on` : en YAML, une clé `on` toute seule est lue comme le
booléen `true`.

### `upload` : envoyer un fichier

Met des fichiers dans un champ `<input type=file>`, comme si on les avait choisis dans
l'explorateur.

| Option | Défaut | Rôle |
| --- | --- | --- |
| `files` | **obligatoire** | Liste de chemins, **relatifs au fichier de scénario**. Ex. `[fixtures/e2e-cube.glb]` |

```yaml
      - click: { role: button, name: Import assets }
      - upload: { css: "input[type=file][accept*='.glb']" }
        files: [fixtures/cemetery_angel_-_miller.glb]
      - click: { role: button, name: Import model }
```

### `drag` : glisser-déposer

Glisse l'élément `drag` et le lâche sur l'élément `to`.

| Option | Défaut | Rôle |
| --- | --- | --- |
| `to` | **obligatoire** | La cible où lâcher |
| `to_position` | centre de `to` | `{ x, y }` : le point d'arrivée, en pixels depuis le coin haut-gauche de `to` |
| `to_offset` | | `{ x, y }` : le point d'arrivée, en pixels depuis le **centre** de `to` (négatif = vers la gauche ou le haut). À la place de `to_position` |
| `from_offset` | centre de `drag` | `{ x, y }` : le point où l'on appuie, en pixels depuis le centre de `drag`. Sert à viser une poignée de gizmo à côté de l'objet, ou un coin vide du viewport pour tirer un rectangle de sélection |
| `steps` | | Fait le glissé en N petits mouvements de souris (ex. `12`). **Obligatoire dans l'éditeur de nœuds** (onglet Scripting) et dans le viewport 3D, qui ignorent un glissé fait d'un seul saut. Sans `steps`, c'est un glisser-déposer HTML classique, qui convient aux assets et aux scripts déposés sur l'Inspector |
| `button` | `left` | Le bouton tenu pendant le glissé : `left`, `right` (regarder autour dans le viewport 3D) ou `middle` (déplacer la vue). Demande `steps` |
| `timeout` | celui de la suite | Attente maximale |

```yaml
      # Poser un asset dans la scène
      - drag: { role: listitem, has_text: e2e-cube }
        to: { id: scene-view-canvas }
      # Déplacer un nœud dans l'éditeur de scripts
      - drag: { css: ".svelte-flow__node-value_node .dragHandle" }
        to: { css: ".svelte-flow__pane" }
        to_position: { x: 210, y: 480 }
        steps: 12
      # Relier deux nœuds : tirer un fil d'une sortie vers une entrée
      - drag: { css: "[data-handleid=value_node_source_1]" }
        to: { css: "[data-handleid=rotate_node_target_3]" }
        steps: 12
      # Rectangle de sélection dans le viewport : d'un coin à l'autre, autour du centre
      - drag: { id: scene-view-canvas }
        from_offset: { x: -320, y: -230 }
        to: { id: scene-view-canvas }
        to_offset: { x: 320, y: 230 }
        steps: 20
      # Regarder autour : clic droit maintenu
      - drag: { id: scene-view-canvas }
        to: { id: scene-view-canvas }
        to_offset: { x: 120, y: 0 }
        button: right
        steps: 20
```

### `choose` : choisir dans une liste déroulante

Choisit une option d'un `<select>` natif, par sa valeur ou son texte affiché.

| Option | Défaut | Rôle |
| --- | --- | --- |
| `option` | **obligatoire** | La valeur ou le libellé de l'option |
| `timeout` | celui de la suite | Attente maximale |

```yaml
      - choose: { css: ".svelte-flow__node-value_node select" }
        option: float
```

Les menus faits en HTML (rôles `menu`, `listbox`) ne sont pas des `<select>` : on clique dessus,
puis sur l'option (`click: { role: menuitem, name: … }`).

### `wait` : attendre

Une pause fixe. La valeur est une durée (`2s`, `500ms`).

```yaml
      - wait: 2s                 # laisse voir la scène chargée
```

Pour **attendre que quelque chose arrive**, préférer un `expect` : il attend juste le temps
nécessaire, et échoue avec un message clair. `wait` ne sert qu'à laisser le temps de **voir**
(pendant qu'on regarde le test) ou à laisser un plantage se produire avant la fin d'une feature.

### `reload` : recharger la page

```yaml
      - reload: true
```

À éviter dans l'éditeur : un rechargement relance le moteur et ressemble à un bug pour qui
regarde le test.

### `screenshot` : capture d'écran

Enregistre une capture dans `runs/<run id>/screenshots/<feature>-<nom>.png`. Elle apparaît dans
le rapport, sous l'étape.

| Option | Défaut | Rôle |
| --- | --- | --- |
| `of` | toute la page | Une cible : la capture ne contient que cet élément (ex. le canvas du jeu) |

Le nom ne contient que des lettres, chiffres, `-`, `_`, `.`.

```yaml
      - screenshot: game
        of: { id: game-view-canvas }
```

### `store` : mémoriser une valeur

Mémorise une valeur sous un nom, pour la réutiliser ensuite en `${var.<nom>}`. Il faut
**exactement une** des trois sources :

| Source | Ce qui est mémorisé |
| --- | --- |
| `url_pattern` | Le premier groupe entre parenthèses d'une expression régulière, appliquée à l'URL de la page. Ex. `"id=([0-9a-f]+)"` |
| `text_of` | Le texte affiché d'une cible |
| `js` | Le résultat d'un code JavaScript exécuté dans la page. Il peut être asynchrone, par exemple un `fetch` |

```yaml
      - store: project_id
        url_pattern: "id=([0-9a-f]+)"
      - store: coins_before
        js: "() => fetch('${base.api}/users/me', { credentials: 'include' }).then(r => r.json()).then(u => u.money ?? 0)"
      - expect:
          js: "async () => ((await (await fetch('${base.api}/users/me', { credentials: 'include' })).json()).money ?? 0) >= ${var.coins_before} + 500"
```

### `expect_response` : exiger une réponse réseau

Option de `goto` et `click` : l'action doit déclencher une réponse réseau qui correspond, sinon
l'étape échoue.

| Champ | Défaut | Rôle |
| --- | --- | --- |
| `url` | **obligatoire** | Motif de l'adresse : `*` et `**` remplacent n'importe quoi. Ex. `"**/catalog/*/lookup"` |
| `method` | toutes | `GET`, `POST`, `PUT`… |
| `status` | `2xx` | Un code exact (`201`) ou une famille (`2xx`, `4xx`) |
| `timeout` | `30s` | Attente maximale de la réponse |

En cas d'échec, le rapport donne le code reçu **et le début de la réponse du serveur**, qui
explique souvent le refus :

```
POST https://api.play-horizon.games/convert answered 400, expected 2xx: {"error":"invalid input: conversion failed: glTF error: …"}
```

## 6. Les cibles : désigner un élément

Une cible s'écrit entre accolades et désigne **un élément** de la page. Elle a **une seule
base**, et éventuellement des **précisions**.

### Les bases (une seule par cible)

Par ordre de préférence, de la plus solide à la plus fragile :

| Base | Trouve | Exemple |
| --- | --- | --- |
| `testid` | L'attribut `data-testid` | `{ testid: payment-form-submit-button }` |
| `role` (+ `name`) | Un élément par son rôle d'accessibilité : `button`, `tab`, `treeitem`, `menuitem`, `heading`, `dialog`, `alert`, `listitem`, `spinbutton`, `textbox`… et son nom affiché | `{ role: button, name: Sign In }` |
| `label` | Un champ par son libellé | `{ label: Email }` |
| `text` | Un élément par son texte | `{ text: Script saved }` |
| `placeholder` | Un champ par son texte d'exemple | `{ placeholder: Search nodes... }` |
| `title` | Un élément par son attribut `title` (l'infobulle) | `{ title: Delete Project }` |
| `id` | Un élément par son `id` | `{ id: scene-view-canvas }` |
| `css` | Un sélecteur CSS, en dernier recours | `{ css: "[data-slot=hierarchy-view]" }` |

### Les précisions

| Précision | Rôle | Exemple |
| --- | --- | --- |
| `exact: true` | Le texte (`name`, `label`, `text`, `placeholder`, `title`) doit correspondre exactement. Sans ça : « contient », sans tenir compte des majuscules | `{ role: menuitem, name: Cube, exact: true }` (sinon « Cube » trouverait aussi « Cubemap ») |
| `within: <cible>` | Chercher seulement à l'intérieur d'un autre élément | `{ role: treeitem, within: { css: "[data-slot=hierarchy-view]" } }` |
| `has_text: …` | Garder seulement les éléments qui contiennent ce texte | `{ role: listitem, has_text: e2e-cube }` |
| `has: <cible>` | Garder seulement les éléments qui contiennent cet autre élément | `{ css: div.group, has: { role: heading, name: Mon jeu } }` |
| `nth` | Choisir parmi plusieurs : `first`, `last`, ou un numéro à partir de 0 | `{ role: button, name: Create New Game, nth: first }` |
| `frame` | Chercher dans une iframe, désignée par son sélecteur CSS. S'applique avant `within` | `{ frame: "iframe[src*='js.stripe.com/v3/elements-inner']:visible", id: payment-numberInput }` |

**Plusieurs éléments trouvés = erreur.** Sans `nth`, une cible qui correspond à deux éléments
fait échouer l'étape (`strict mode violation … resolved to 2 elements`). C'est voulu : un clic
ne doit jamais tomber sur le mauvais bouton. On précise alors la cible avec `within`, `has_text`,
`exact` ou `nth`.

### Réutiliser une cible : les ancres YAML

Une cible longue se nomme une fois avec `&nom`, puis se réutilise avec `*nom` :

```yaml
      - fill: &position_x { role: spinbutton, name: X, within: { css: div.flex-col, has: { css: ":scope > span", has_text: position }, nth: last } }
        value: "5"
      - press: Enter
        target: *position_x
      - expect: { target: *position_x, number: 5 }
```

Une ancre doit être définie **plus haut dans le fichier** que son premier usage.

## 7. Les vérifications (`expect`)

`expect` vérifie un état. Il **réessaie jusqu'au `timeout`** : pas besoin de `wait` avant. Une
même étape peut combiner plusieurs vérifications, qui doivent toutes passer.

### Sur un élément (avec `target`)

| Vérification | Passe quand… | Exemple |
| --- | --- | --- |
| `visible: true` / `false` | l'élément est affiché / absent ou caché | `{ target: { role: heading, name: Welcome back }, visible: true }` |
| `text: …` | son texte **contient** celui-ci | `{ target: { role: alert }, text: conversion failed }` |
| `value: …` | la valeur du champ est **exactement** celle-ci | `{ target: { label: Script name }, value: Untitled script }` |
| `number: …` (+ `tolerance`) | la valeur (ou le texte), lue comme un nombre, vaut celui-ci à `tolerance` près (défaut 0,001). Pour les valeurs du moteur : une rotation de 45 revient en 45.000004 | `{ target: *rotation_y, number: 45, tolerance: 0.01 }` |
| `count: N` | la cible trouve exactement N éléments (`0` = aucun) | `{ target: { role: treeitem, has_text: Cube }, count: 2 }` |
| `enabled: true` / `false` | l'élément est actif / désactivé | |
| `checked: true` / `false` | la case ou le bouton radio est coché / décoché | `{ target: { css: "input[value=rotate]" }, checked: true }` |
| `rendered: true` / `false` | l'élément **dessine quelque chose** : au moins 0,5 % de ses pixels diffèrent de sa couleur dominante. `false` : il est uni (vide, noir). Pour les canvas du jeu, qu'on ne peut pas lire autrement | `{ target: { id: game-view-canvas }, rendered: true, timeout: 30s }` |
| `animated: true` / `false` | deux captures prises à 500 ms d'écart **diffèrent** (au moins 0,05 % des pixels) : quelque chose bouge. `false` : l'image reste fixe | `{ target: { id: game-view-canvas }, animated: true }` |
| `dominant_color: "#RRGGBB"` (+ `color_tolerance`) | la couleur la plus fréquente de l'élément est celle-ci, à `color_tolerance` près par canal (défaut 12). Ex. le fond du jeu | `{ target: { id: game-view-canvas }, dominant_color: "#3366CC" }` |

### Sur la page (sans `target`)

| Vérification | Passe quand… | Exemple |
| --- | --- | --- |
| `url: …` | l'adresse correspond au motif (`*` et `**` = n'importe quoi) | `{ url: "**/editor?id=*", timeout: 20s }` |
| `title: …` | le titre de l'onglet **contient** ce texte | `{ title: "e2e-${run.id} en cours" }` |
| `console: regex` | un message de la console correspond, **depuis le dernier chargement de page** | `{ console: "backend: BrowserWebGpu", timeout: 60s }` |
| `no_console: regex` | **aucun** message ne correspond depuis le début de la feature. Échoue en citant le message trouvé | `{ no_console: "doesn't match the expected dimension" }` |
| `js: …` | un code JavaScript renvoie une valeur vraie. Il peut être asynchrone | `{ js: "() => document.querySelectorAll('.svelte-flow__edge').length >= 3" }` |

### Option commune

| Option | Défaut | Rôle |
| --- | --- | --- |
| `timeout` | celui de la suite | Jusqu'à quand réessayer |

## 8. Durées, pièges YAML, validation

### Durées

Une durée s'écrit `500ms`, `30s`, `2m`, ou un nombre seul (en secondes). Elle sert pour
`timeout`, `wait` et `expect_response.timeout`.

### Pièges YAML

| Piège | Solution |
| --- | --- |
| `${…}` dans des accolades `{ }` | Entre guillemets : `{ role: heading, name: "e2e-${run.id}" }` |
| Un nombre à saisir (`value: 5`) | Entre guillemets : `value: "5"` (c'est un texte qu'on tape) |
| Une couleur (`#3366CC`) | Entre guillemets, sinon `#` commence un commentaire : `"#3366CC"` |
| Une clé `on:` | Lue comme `true` : c'est pour ça que `press` utilise `target:` |
| Un antislash dans une regex | Doublé entre guillemets doubles : `"^\\[pageerror\\]"`, `"\\(TextureViewDimension::Cube\\)"` |
| Un texte long (prompt…) | Bloc replié : `value: >-` puis le texte sur les lignes suivantes, indenté |
| L'indentation des options | Les options d'une étape s'alignent sous le nom de l'action, pas sous le tiret |

### Valider et tester

```powershell
.venv\Scripts\horizon-analyzer validate scenarios\mon-scenario.yaml   # vérifie le fichier, sans navigateur
.venv\Scripts\horizon-analyzer run scenarios\mon-scenario.yaml --only MA-FEATURE   # une feature + ses dépendances
.venv\Scripts\horizon-analyzer run scenarios\mon-scenario.yaml --slow-mo 300       # au ralenti, pour suivre
```

Quand une étape échoue, le rapport (`runs/<run id>/report.html`) donne l'étape, la raison, une
capture de la page au moment de l'échec, et les erreurs console.

**Trouver une bonne cible.** Ouvrir la page dans Chrome, clic droit > Inspecter sur l'élément,
puis chercher dans l'ordre : un `data-testid`, un rôle avec un nom visible (bouton, onglet,
ligne), un libellé, un `id`. Le CSS ne vient qu'en dernier, parce qu'il casse dès que la mise en
page change.

## 9. Exemple complet commenté

Une suite qui crée un projet, y ajoute un cube, vérifie qu'il s'affiche dans le jeu, puis
supprime le projet.

```yaml
# yaml-language-server: $schema=./horizon-analyzer.schema.json
suite: exemple-cube
description: Ajouter un cube et le voir en jeu.
base_urls:
  editor: https://editor.play-horizon.games
locale: fr-FR
timeout: 15s
fail_on_console:
  - "panicked at"                          # le moteur a planté : la feature est KO

features:
  # Connexion : sert à toutes les features suivantes (même page)
  - id: LOGIN
    name: Connexion
    steps:
      - goto: ${base.editor}/
      - fill: { label: Email }
        value: ${env.HORIZON_EMAIL}        # lu dans .env, masqué dans le rapport
      - fill: { label: Password, exact: true }
        value: ${env.HORIZON_PASSWORD}
      - click: { role: button, name: Sign In }
        expect_response: { url: "**/login", method: POST, status: 2xx }
      - expect: { target: { role: heading, name: Welcome back }, visible: true }

  # Un projet au nom unique, supprimé en fin de run
  - id: PROJECT
    name: Créer un projet
    mutating: true
    depends_on: [LOGIN]
    steps:
      - click: { role: button, name: Create New Game, nth: first }
      - fill: { id: modal-game-name }
        value: e2e-${run.id}
      - click: { role: button, name: Create Game }
      - expect: { url: "**/editor?id=*", timeout: 20s }
      - expect: { console: "backend: BrowserWebGpu", timeout: 60s }   # le moteur a démarré
    cleanup:
      - goto: ${base.editor}/
      - hover: { role: heading, name: "e2e-${run.id}", exact: true }
      - click: { title: Delete Project, within: { css: div.group, has: { role: heading, name: "e2e-${run.id}", exact: true }, nth: first } }

  # Un cube, une lumière, une caméra reculée
  - id: SCENE
    name: Monter la scène
    mutating: true
    depends_on: [PROJECT]
    requires_webgpu: true
    steps:
      - click: &tree { css: "[data-slot=hierarchy-view]" }
        button: right
        position: { x: 100, y: 400 }
      - click: { role: menuitem, name: Cube, exact: true }
      - click: *tree
        button: right
        position: { x: 100, y: 400 }
      - click: { role: menuitem, name: Directional Light, exact: true }
      - click: *tree
        button: right
        position: { x: 100, y: 400 }
      - click: { role: menuitem, name: Camera, exact: true }
      - select: { role: treeitem, within: *tree, has_text: Camera }
      - fill: &cam_z { role: spinbutton, name: Z, within: { css: div.flex-col, has: { css: ":scope > span", has_text: position }, nth: last } }
        value: "6"
      - press: Enter
        target: *cam_z
      - expect: { target: *cam_z, number: 6 }

  # Le jeu affiche le cube ; on l'arrête quoi qu'il arrive
  - id: PLAY
    name: Le cube s'affiche en jeu
    depends_on: [SCENE]
    requires_webgpu: true
    steps:
      - click: { role: button, name: Play, exact: true }
      - expect: { target: { role: button, name: Stop, exact: true }, visible: true, timeout: 60s }
      - expect: { target: &game { id: game-view-canvas }, rendered: true, timeout: 30s }
      - screenshot: game
        of: *game
    teardown:
      - click: { role: button, name: Stop, exact: true }
        force: true                        # même si le jeu ne s'est pas lancé
```

Les scénarios livrés sont aussi de bons modèles : chaque feature y est précédée d'un commentaire
qui dit ce qu'elle teste.
- [critical.yaml](../scenarios/critical.yaml) : connexion, éditeur, publication, paiement Stripe, launcher.
- [engine.yaml](../scenarios/engine.yaml) : scripts no-code et IA, lumière, ombres, matériaux, cas KO avec `teardown`.
- [atp.yaml](../scenarios/atp.yaml) : les 78 features de l'ATP, dont l'inscription par e-mail, les gizmos (`from_offset`), la caméra de l'éditeur (`button: right`, `hold`), chaque champ des composants.
