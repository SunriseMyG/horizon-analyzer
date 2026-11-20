"""Run outputs: report.json (machine), report.html (people), junit.xml (CI), and the webhook alert."""

from __future__ import annotations

import html
import json
import urllib.request
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree

from horizon_analyzer.runner import FeatureResult, RunResult, Status

_LABELS = {
    Status.PASSED: "OK",
    Status.FAILED: "Échec",
    Status.BLOCKED: "Bloqué",
    Status.SKIPPED: "Sauté",
}


def write_reports(result: RunResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "report.html").write_text(render_html(result, out_dir), encoding="utf-8")
    render_junit(result).write(out_dir / "junit.xml", encoding="utf-8", xml_declaration=True)


def summary_line(result: RunResult) -> str:
    counts = ", ".join(f"{result.count(status)} {status.value}" for status in Status if result.count(status))
    return f"{result.suite} [{result.run_id}]: {counts} in {result.duration:g}s"


def render_junit(result: RunResult) -> ElementTree.ElementTree:
    suite = ElementTree.Element(
        "testsuite",
        name=result.suite,
        tests=str(len(result.features)),
        failures=str(result.count(Status.FAILED)),
        errors=str(result.count(Status.BLOCKED)),
        skipped=str(result.count(Status.SKIPPED)),
        time=f"{result.duration:.2f}",
        timestamp=result.started_at,
    )
    for feature in result.features:
        case = ElementTree.SubElement(suite, "testcase", classname=result.suite, name=f"{feature.id} {feature.name}", time=f"{feature.duration:.2f}")
        if feature.status is Status.FAILED:
            failed = next((step for step in feature.steps if step.status is Status.FAILED), None)
            node = ElementTree.SubElement(case, "failure", message=feature.reason or "failed")
            node.text = failed.error if failed else None
        elif feature.status is Status.BLOCKED:
            ElementTree.SubElement(case, "error", message=feature.reason or "blocked")
        elif feature.status is Status.SKIPPED:
            ElementTree.SubElement(case, "skipped", message=feature.reason or "skipped")
    return ElementTree.ElementTree(suite)


def render_html(result: RunResult, out_dir: Path) -> str:
    rows = "\n".join(_feature_html(feature, out_dir) for feature in result.features)
    cleanup = ""
    if result.cleanup:
        items = "".join(
            f"<li class='{'bad' if entry.error else 'good'}'>{html.escape(entry.feature_id)} · {html.escape(entry.description)}"
            + (f"<pre>{html.escape(entry.error)}</pre>" if entry.error else "")
            + "</li>"
            for entry in result.cleanup
        )
        cleanup = f"<h2>Nettoyage</h2><ul class='cleanup'>{items}</ul>"
    tiles = "".join(
        f"<div class='tile {status.value}'><b>{result.count(status)}</b>{_LABELS[status]}</div>" for status in Status
    )
    trace = (
        "<p class='muted'>Trace complète : <code>playwright show-trace trace.zip</code> dans ce dossier.</p>"
        if (out_dir / "trace.zip").exists()
        else ""
    )
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(result.suite)} · {html.escape(result.run_id)}</title>
<style>{_CSS}</style></head><body><main>
<h1>{html.escape(result.suite)}</h1>
<p class="muted">Run {html.escape(result.run_id)} · {html.escape(result.started_at)} · {result.duration:g}s · {html.escape(result.browser)}</p>
<div class="tiles">{tiles}</div>
{trace}
<h2>Features</h2>
{rows}
{cleanup}
</main></body></html>"""


def _feature_html(feature: FeatureResult, out_dir: Path) -> str:
    steps = "".join(
        f"<tr class='{step.status.value}'><td>{step.index}</td><td>{html.escape(step.description)}</td>"
        f"<td>{step.duration:g}s</td><td>{_LABELS[step.status]}</td></tr>"
        + (f"<tr class='err'><td></td><td colspan='3'><pre>{html.escape(step.error)}</pre></td></tr>" if step.error else "")
        + "".join(
            f"<tr><td></td><td colspan='3'><a href='{html.escape(path)}'><img src='{html.escape(path)}' alt='{html.escape(path)}'></a></td></tr>"
            for path in step.attachments
        )
        for step in feature.steps
    )
    reason = f"<p class='reason'>{html.escape(feature.reason)}</p>" if feature.reason else ""
    shot = (
        f"<a href='{html.escape(feature.screenshot)}'><img src='{html.escape(feature.screenshot)}' alt='capture au moment de l’échec'></a>"
        if feature.screenshot
        else ""
    )
    console = (
        "<details><summary>Erreurs console ({})</summary><pre>{}</pre></details>".format(
            len(feature.console_errors), html.escape("\n".join(line[:400] for line in feature.console_errors[:30]))
        )
        if feature.console_errors
        else ""
    )
    table = f"<table><tbody>{steps}</tbody></table>" if steps else ""
    tags = " ".join(f"<span class='tag'>{html.escape(tag)}</span>" for tag in feature.tags)
    is_open = " open" if feature.status is not Status.PASSED else ""
    return (
        f"<details class='feature {feature.status.value}'{is_open}><summary><span class='badge'>{_LABELS[feature.status]}</span>"
        f"<b>{html.escape(feature.id)}</b> {html.escape(feature.name)} {tags}<span class='muted right'>{feature.duration:g}s</span></summary>"
        f"{reason}{table}{shot}{console}</details>"
    )


_CSS = """
:root{--bg:#fafafa;--fg:#1c1c1e;--muted:#6b6b70;--card:#fff;--line:#e4e4e7;--good:#1f8a4c;--bad:#c62828;--warn:#b26a00;--skip:#6b6b70}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--fg:#ececef;--muted:#9a9aa1;--card:#1d1d20;--line:#2e2e33;--good:#4cc27e;--bad:#ff6b6b;--warn:#f0a83a;--skip:#9a9aa1}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px}
h1{margin:0 0 4px}h2{margin-top:32px}.muted{color:var(--muted)}.right{float:right}
.tiles{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 16px;min-width:90px}
.tile b{display:block;font-size:24px}.tile.passed b{color:var(--good)}.tile.failed b{color:var(--bad)}.tile.blocked b{color:var(--warn)}.tile.skipped b{color:var(--skip)}
.feature{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--skip);border-radius:8px;margin:8px 0;padding:8px 12px}
.feature.passed{border-left-color:var(--good)}.feature.failed{border-left-color:var(--bad)}.feature.blocked{border-left-color:var(--warn)}
summary{cursor:pointer}.badge{display:inline-block;min-width:56px;font-size:12px;font-weight:600}
.passed .badge{color:var(--good)}.failed .badge{color:var(--bad)}.blocked .badge{color:var(--warn)}.skipped .badge{color:var(--skip)}
.tag{font-size:11px;border:1px solid var(--line);border-radius:999px;padding:0 6px;color:var(--muted)}
table{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}td{padding:4px 6px;border-top:1px solid var(--line);vertical-align:top}
tr.failed td{color:var(--bad)}pre{white-space:pre-wrap;word-break:break-word;font-size:12px;margin:0}
img{max-width:100%;border:1px solid var(--line);border-radius:6px;margin-top:8px}
.reason{color:var(--muted);margin:6px 0}.cleanup li.bad{color:var(--bad)}
"""


def send_webhook(url: str, result: RunResult, report_path: Path) -> None:
    """Post a short message to a Discord or Slack incoming webhook. Failures here never fail the run."""
    lines = [f"Horizon analyzer: {summary_line(result)}"]
    for feature in result.features:
        if feature.status in (Status.FAILED, Status.BLOCKED):
            lines.append(f"- {feature.id} {_LABELS[feature.status]}: {feature.reason}")
    lines.append(f"Rapport : {report_path}")
    message = "\n".join(lines)[:1900]
    body = json.dumps({"content": message, "text": message}).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "horizon-analyzer"})
    try:
        urllib.request.urlopen(request, timeout=10).close()
    except OSError as error:
        print(f"warning: webhook not delivered: {error}")
