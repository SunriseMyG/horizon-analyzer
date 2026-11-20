"""Reading scenario files and resolving the ``${namespace.name}`` variables inside them."""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from horizon_analyzer.schema import Suite

_VARIABLE = re.compile(r"\$\{\s*(env|var|run|base)\.([A-Za-z0-9_-]+)\s*\}")


class ScenarioError(Exception):
    """The scenario file can't be read or doesn't match the format."""


def load_suite(path: Path) -> Suite:
    """Read a YAML or JSON scenario file and validate it."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ScenarioError(f"cannot read {path}: {error}") from None
    try:
        data = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise ScenarioError(f"{path} is not valid {path.suffix.lstrip('.').upper() or 'YAML'}: {error}") from None
    if not isinstance(data, dict):
        raise ScenarioError(f"{path}: the top level must be a mapping with 'suite' and 'features'")
    try:
        return Suite.model_validate(data)
    except ValidationError as error:
        lines = [f"{path} does not match the scenario format:"]
        for item in error.errors():
            where = _location(data, item["loc"])
            lines.append(f"  - {where}: {item['msg'].removeprefix('Value error, ')}")
        raise ScenarioError("\n".join(lines)) from None


def _location(data: dict[str, Any], loc: tuple[Any, ...]) -> str:
    """Name a validation error's position by feature id rather than by list index."""
    parts: list[str] = []
    node: Any = data
    for part in loc:
        if isinstance(node, list) and isinstance(part, int) and part < len(node):
            item = node[part]
            label = item.get("id") if isinstance(item, dict) and "id" in item else None
            parts.append(f"[{label}]" if label else f"[{part + 1}]")
            node = item
        else:
            parts.append(f".{part}" if parts else str(part))
            node = node.get(part) if isinstance(node, dict) else None
    return "".join(parts) or "file"


def load_dotenv(path: Path) -> None:
    """Load ``KEY=value`` lines into the environment without overriding variables already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def new_run_id() -> str:
    """A short id unique per run, safe in names and URLs: ``20261119-1503-a1b2``."""
    return f"{datetime.now():%Y%m%d-%H%M}-{secrets.token_hex(2)}"


def referenced_variables(suite: Suite) -> set[tuple[str, str]]:
    """Every ``(namespace, name)`` the suite refers to."""
    return {(match.group(1), match.group(2)) for match in _VARIABLE.finditer(suite.model_dump_json())}


@dataclass
class Context:
    """Run-wide values the scenario refers to, and the secrets to mask in every output."""

    suite: Suite
    base_dir: Path
    run_id: str
    variables: dict[str, str] = field(default_factory=dict)
    secret_values: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.variables = {**self.suite.vars, **self.variables}

    def render(self, text: str) -> str:
        """Replace every ``${...}`` in ``text``. Values read from the environment count as secrets."""

        def replace(match: re.Match[str]) -> str:
            namespace, name = match.group(1), match.group(2)
            if namespace == "env":
                value = os.environ.get(name)
                if value is None:
                    raise ScenarioError(f"environment variable {name} is not set (put it in .env)")
                if value:
                    self.secret_values.add(value)
                return value
            if namespace == "run":
                if name != "id":
                    raise ScenarioError(f"unknown ${{run.{name}}}: only ${{run.id}} exists")
                return self.run_id
            if namespace == "base":
                if name not in self.suite.base_urls:
                    raise ScenarioError(f"unknown base url {name!r}; declare it under base_urls")
                return self.suite.base_urls[name].rstrip("/")
            if name not in self.variables:
                raise ScenarioError(f"${{var.{name}}} is not defined yet (declare it under vars or store it first)")
            return self.variables[name]

        return _VARIABLE.sub(replace, text)

    def mask(self, text: str) -> str:
        """Hide every secret value in ``text``."""
        for value in sorted(self.secret_values, key=len, reverse=True):
            text = text.replace(value, "***")
        return text

    def resolve_file(self, relative: str) -> Path:
        path = (self.base_dir / self.render(relative)).resolve()
        if not path.is_file():
            raise ScenarioError(f"file {relative!r} not found (looked for {path})")
        return path
