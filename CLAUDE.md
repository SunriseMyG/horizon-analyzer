# CLAUDE.md

Le guide complet du projet est dans AGENTS.md (partagé avec les autres agents) :

@AGENTS.md

## En plus, pour Claude Code

- Réponds à l'utilisateur en français.
- Avant un run contre la prod, vérifie qu'aucun autre run ne tourne : les runs partagent le
  compte de test. Un run critique ouvre une fenêtre et prend 1 à 3 min : lance-le en arrière-plan
  et attends sa notification, sans sonder sa sortie en boucle.
- Après un run interrompu ou en échec, lance `scripts/check_leftovers.py` et signale les restes
  `e2e-*` avant de passer à autre chose.
- Pour enquêter sur un comportement de prod, écris des scripts jetables dans le scratchpad
  (Playwright direct, ou un `PlaywrightExecutor` sous-classé qui logue console, requêtes et
  navigations), plutôt que de modifier les scénarios pour tester une hypothèse.
- Regarde les captures `runs/<id>/failures/*.png` avec l'outil Read avant de conclure sur la
  cause d'un échec.
- Pour vérifier une modification : `pytest -q`, `horizon-analyzer validate`, puis un run réel
  (`--only <feature>` si la modification est locale).
