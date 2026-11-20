"""Liste ce qu'un run interrompu a pu laisser sur le compte de test (lecture seule).

Affiche les projets de l'éditeur et les jeux du store dont le nom commence par « e2e- », et le
solde de pièces. Un run normal ne laisse rien : son nettoyage dépublie le jeu et supprime le
projet. Ce qui reste vient d'un run coupé (navigateur fermé, réseau perdu) et se supprime à la
main depuis l'accueil de l'éditeur (« Edit » > « Unpublish Game », puis l'icône de suppression).

Usage : .venv\\Scripts\\python scripts\\check_leftovers.py   (lit HORIZON_EMAIL/PASSWORD dans .env)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from horizon_analyzer.loader import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
EDITOR = "https://editor.play-horizon.games/"
LAUNCHER = "https://play.play-horizon.games/"
API = "https://api.play-horizon.games"


def sign_in(page: Page, url: str) -> None:
    page.goto(url)
    page.get_by_label("Email").fill(os.environ["HORIZON_EMAIL"])
    page.get_by_label("Password", exact=True).fill(os.environ["HORIZON_PASSWORD"])
    page.get_by_role("button", name="Sign In").click()


def main() -> int:
    load_dotenv(ROOT / ".env")
    if not os.environ.get("HORIZON_EMAIL") or not os.environ.get("HORIZON_PASSWORD"):
        print("HORIZON_EMAIL / HORIZON_PASSWORD manquants : copier .env.example en .env et le remplir")
        return 2
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        editor = browser.new_page()
        sign_in(editor, EDITOR)
        editor.get_by_role("heading", name="Welcome back").wait_for()
        editor.wait_for_timeout(2000)  # the project cards load after the heading
        projects = sorted(set(editor.locator("h3").all_inner_texts()))

        launcher = browser.new_page(locale="fr-FR")
        sign_in(launcher, LAUNCHER)
        launcher.get_by_placeholder("Rechercher des jeux, créateurs, genres...").wait_for()
        launcher.wait_for_timeout(2000)
        games = sorted(set(launcher.locator("h3").all_inner_texts()))
        money = launcher.evaluate(f"() => fetch('{API}/users/me', {{credentials: 'include'}}).then(r => r.json()).then(u => u.money)")
        browser.close()

    leftovers = [name for name in projects if name.startswith("e2e-")]
    published = [name for name in games if name.startswith("e2e-")]
    print("projets       :", ", ".join(projects) or "(aucun)")
    print("jeux du store :", ", ".join(games) or "(aucun)")
    print("pièces        :", money)
    if leftovers or published:
        print("RESTES e2e    : projets", leftovers, "| publiés", published)
        return 1
    print("aucun reste e2e")
    return 0


if __name__ == "__main__":
    sys.exit(main())
