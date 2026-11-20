"""Command line: ``horizon-analyzer run|validate|schema``."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from horizon_analyzer.loader import Context, ScenarioError, load_dotenv, load_suite, new_run_id, referenced_variables
from horizon_analyzer.report import send_webhook, summary_line, write_reports
from horizon_analyzer.runner import Status, run_suite, select_features
from horizon_analyzer.schema import Suite, json_schema

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Rejoue les parcours critiques d'Horizon décrits dans un fichier de scénarios.")

_SYMBOLS = {Status.PASSED: "OK  ", Status.FAILED: "FAIL", Status.BLOCKED: "BLOC", Status.SKIPPED: "SKIP"}

# Windows consoles default to a legacy code page; reports and messages are UTF-8.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def _split(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    return {item.strip() for value in values for item in value.split(",") if item.strip()}


def _load(scenario: Path) -> tuple[Suite, Path]:
    try:
        return load_suite(scenario), scenario.resolve().parent
    except ScenarioError as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from None


@app.command()
def run(
    scenario: Annotated[Path, typer.Argument(help="Fichier de scénarios (.yaml ou .json)")],
    tags: Annotated[list[str] | None, typer.Option("--tags", "-t", help="Ne lancer que ces tags (séparés par des virgules)")] = None,
    only: Annotated[list[str] | None, typer.Option("--only", "-o", help="Ne lancer que ces features (et leurs dépendances)")] = None,
    safe_only: Annotated[bool, typer.Option("--safe-only", help="Exclure les features qui écrivent en prod")] = False,
    headless: Annotated[bool, typer.Option("--headless", help="Sans fenêtre (WebGPU logiciel, instable pour la 3D)")] = False,
    slow_mo: Annotated[int, typer.Option("--slow-mo", help="Pause en ms entre chaque action, pour suivre à l'œil")] = 0,
    out: Annotated[Path, typer.Option("--out", help="Dossier des runs")] = Path("runs"),
    trace: Annotated[bool, typer.Option("--trace/--no-trace", help="Enregistrer une trace Playwright")] = True,
    cache: Annotated[
        bool, typer.Option("--cache/--no-cache", help="Garder sur disque le code et le wasm d'Horizon (fichiers versionnés) d'un run à l'autre")
    ] = True,
    env_file: Annotated[Path, typer.Option("--env-file", help="Fichier de secrets")] = Path(".env"),
    webhook: Annotated[str | None, typer.Option("--webhook", help="Webhook Discord/Slack (défaut : HORIZON_WEBHOOK_URL)")] = None,
) -> None:
    """Lance les features du fichier, dans l'ordre, et écrit le rapport."""
    from horizon_analyzer.browser import BrowserOptions, PlaywrightExecutor

    load_dotenv(env_file)
    suite, base_dir = _load(scenario)
    try:
        features = select_features(suite, tags=_split(tags), only=_split(only), safe_only=safe_only)
    except ScenarioError as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from None
    if not features:
        typer.secho("aucune feature ne correspond aux filtres", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(2)

    context = Context(suite=suite, base_dir=base_dir, run_id=new_run_id())
    out_dir = out / context.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    typer.echo(f"{suite.suite}: {len(features)} feature(s), run {context.run_id}")

    options = BrowserOptions(headless=headless, slow_mo=slow_mo, trace=trace, asset_cache=out / ".cache" if cache else None)
    with PlaywrightExecutor(context, out_dir, options) as executor:
        result = run_suite(suite, features, executor, context)
        result.browser = executor.browser_description  # includes the WebGPU adapter once probed
        if executor.window_restores:
            result.browser += f", fenêtre réduite puis restaurée {executor.window_restores} fois"
        if executor.asset_cache is not None:
            cached = executor.asset_cache
            result.browser += f", cache : {cached.hits} fichiers réutilisés, {cached.downloads} téléchargés"
        if executor.closed_tabs:
            result.browser += f", onglets ouverts par le site et refermés : {', '.join(executor.closed_tabs)}"
    write_reports(result, out_dir)

    for feature in result.features:
        line = f"  {_SYMBOLS[feature.status]} {feature.id:<24} {feature.duration:>6.1f}s  {feature.name}"
        color = {Status.PASSED: typer.colors.GREEN, Status.FAILED: typer.colors.RED, Status.BLOCKED: typer.colors.YELLOW}.get(feature.status)
        typer.secho(line, fg=color)
        if feature.reason:
            typer.echo(f"       {feature.reason}")
    for entry in result.cleanup:
        if entry.error:
            typer.secho(f"  nettoyage {entry.feature_id} a échoué ({entry.description}): {entry.error.splitlines()[0]}", fg=typer.colors.YELLOW)
    report = (out_dir / "report.html").resolve()
    typer.echo(summary_line(result))
    typer.echo(f"Rapport : {report}")

    webhook = webhook or os.environ.get("HORIZON_WEBHOOK_URL") or None
    if webhook and not result.ok:
        send_webhook(webhook, result, report)
    raise typer.Exit(0 if result.ok else 1)


@app.command()
def validate(
    scenario: Annotated[Path, typer.Argument(help="Fichier de scénarios (.yaml ou .json)")],
    env_file: Annotated[Path, typer.Option("--env-file", help="Fichier de secrets")] = Path(".env"),
) -> None:
    """Vérifie le fichier (format, dépendances, variables d'environnement) sans ouvrir de navigateur."""
    load_dotenv(env_file)
    suite, _ = _load(scenario)
    missing = sorted(name for namespace, name in referenced_variables(suite) if namespace == "env" and name not in os.environ)
    unknown_bases = sorted(name for namespace, name in referenced_variables(suite) if namespace == "base" and name not in suite.base_urls)
    for name in missing:
        typer.secho(f"variable d'environnement manquante : {name}", fg=typer.colors.RED, err=True)
    for name in unknown_bases:
        typer.secho(f"base url inconnue : {name}", fg=typer.colors.RED, err=True)
    if missing or unknown_bases:
        raise typer.Exit(2)
    steps = sum(len(feature.steps) + len(feature.cleanup) for feature in suite.features)
    typer.secho(f"{scenario}: OK ({len(suite.features)} features, {steps} étapes)", fg=typer.colors.GREEN)


@app.command()
def schema(
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Écrire dans ce fichier au lieu de la sortie")] = None,
) -> None:
    """Affiche le JSON Schema du format (pour l'autocomplétion dans VS Code)."""
    text = json.dumps(json_schema(), indent=2, ensure_ascii=False)
    if output is None:
        typer.echo(text)
    else:
        output.write_text(text + "\n", encoding="utf-8")
        typer.echo(f"écrit : {output}")
