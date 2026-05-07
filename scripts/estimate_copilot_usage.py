#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tiktoken  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    tiktoken = None


BASE_SCENARIOS = ("conservative", "main", "aggressive")
UPPER_SCENARIO = "budget_upper"
SCENARIO_INDEX = {name: index for index, name in enumerate(BASE_SCENARIOS)}

DEFAULT_WORKSPACE_STORAGE_ROOT = (
    Path.home() / "Library/Application Support/Code/User/workspaceStorage"
)
DEFAULT_OUTPUT_ROOT = Path("outputs/copilot-usage")

CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
}

CONFIG_EXTENSIONS = {
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
}

DOC_EXTENSIONS = {
    ".md",
    ".mdx",
    ".rst",
    ".txt",
}

EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".next",
    ".pytest_cache",
    "__pycache__",
    "dist",
    "build",
    "coverage",
    "tmp",
    "outputs",
    "logs",
    ".omc",
    ".claude",
}

EXCLUDED_RELATIVE_PREFIXES = {
    "backend/data",
    "frontend/.next",
    "frontend/out",
}

LINE_COMMENT_PREFIXES = {
    ".py": ("#",),
    ".sh": ("#",),
    ".bash": ("#",),
    ".zsh": ("#",),
    ".yaml": ("#",),
    ".yml": ("#",),
    ".toml": ("#",),
    ".ini": ("#", ";"),
    ".cfg": ("#", ";"),
    ".js": ("//", "/*", "*", "*/"),
    ".jsx": ("//", "/*", "*", "*/"),
    ".ts": ("//", "/*", "*", "*/"),
    ".tsx": ("//", "/*", "*", "*/"),
    ".css": ("/*", "*", "*/"),
    ".scss": ("//", "/*", "*", "*/"),
    ".sass": ("//", "/*", "*", "*/"),
    ".less": ("//", "/*", "*", "*/"),
    ".sql": ("--", "/*", "*", "*/"),
}

BASE_TOOL_HIDDEN_TOKEN_COSTS: dict[str, tuple[int, int, int]] = {
    "copilot_readFile": (600, 1000, 1500),
    "run_in_terminal": (250, 500, 800),
    "copilot_findTextInFiles": (180, 320, 600),
    "copilot_applyPatch": (40, 80, 150),
    "copilot_findFiles": (60, 120, 200),
    "copilot_replaceString": (30, 60, 100),
    "manage_todo_list": (20, 40, 60),
    "copilot_createFile": (20, 40, 80),
    "copilot_listDirectory": (30, 60, 100),
    "copilot_memory": (50, 100, 200),
    "copilot_getErrors": (150, 300, 600),
    "get_terminal_output": (250, 500, 900),
    "search_subagent": (300, 700, 1200),
    "runSubagent": (600, 1500, 3000),
    "configure_python_environment": (80, 150, 250),
    "vscode_fetchWebPage_internal": (200, 500, 1200),
    "copilot_fetchWebPage": (200, 500, 1200),
    "mcp_pylance_mcp_s_pylanceRunCodeSnippet": (120, 250, 500),
    "copilot_viewImage": (100, 300, 800),
    "mcp_microsoft_pla_browser_evaluate": (80, 200, 600),
    "open_browser_page": (20, 40, 60),
    "mcp_microsoft_pla_browser_take_screenshot": (80, 200, 600),
    "mcp_microsoft_pla_browser_snapshot": (120, 300, 800),
    "mcp_microsoft_pla_browser_navigate": (20, 40, 60),
    "kill_terminal": (10, 20, 40),
    "await_terminal": (30, 80, 160),
    "copilot_searchCodebase": (200, 500, 1000),
    "copilot_getChangedFiles": (100, 200, 400),
    "copilot_multiReplaceString": (30, 60, 100),
    "mcp_microsoft_pla_browser_run_code": (120, 300, 700),
}

BASE_REQUEST_OVERHEAD = (4000, 8000, 12000)


def add_vectors(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    if len(left) != len(right):
        raise ValueError("Vector length mismatch")
    return tuple(left[index] + right[index] for index in range(len(left)))


def scale_vector(value: tuple[int, ...], count: int) -> tuple[float, ...]:
    return tuple(item * count for item in value)


def broadcast_vector(value: tuple[float, ...], size: int) -> tuple[float, ...]:
    if len(value) == size:
        return value
    if len(value) > size:
        return value[:size]
    if not value:
        return tuple(0.0 for _ in range(size))
    return tuple(value[index] if index < len(value) else value[-1] for index in range(size))


def vector_to_int_list(value: tuple[float, ...]) -> list[int]:
    return [round(item) for item in value]


def get_scenarios(budget_profile: str) -> tuple[str, ...]:
    if budget_profile == "upper":
        return (*BASE_SCENARIOS, UPPER_SCENARIO)
    return BASE_SCENARIOS


def build_tool_hidden_costs(budget_profile: str) -> dict[str, tuple[int, ...]]:
    if budget_profile != "upper":
        return BASE_TOOL_HIDDEN_TOKEN_COSTS

    upper_costs: dict[str, tuple[int, ...]] = {}
    for tool_name, costs in BASE_TOOL_HIDDEN_TOKEN_COSTS.items():
        upper_costs[tool_name] = (*costs, max(200, round(costs[-1] * 1.5)))
    return upper_costs


def build_request_overhead(budget_profile: str) -> tuple[int, ...]:
    if budget_profile == "upper":
        return (*BASE_REQUEST_OVERHEAD, 16000)
    return BASE_REQUEST_OVERHEAD


def safe_slug(text: str) -> str:
    chars = []
    for char in text.lower():
        if char.isalnum():
            chars.append(char)
        elif chars and chars[-1] != "-":
            chars.append("-")
    slug = "".join(chars).strip("-")
    return slug or "project"


class TokenEstimator:
    def __init__(self) -> None:
        self.mode = "heuristic"
        self._encoder = None
        if tiktoken is not None:
            try:
                self._encoder = tiktoken.get_encoding("o200k_base")
                self.mode = "o200k_base"
            except Exception:
                self._encoder = None

    def estimate(self, text: str) -> tuple[float, float, float]:
        if not text:
            return (0.0, 0.0, 0.0)
        if self._encoder is not None:
            token_count = len(self._encoder.encode(text))
            return (float(token_count), float(token_count), float(token_count))
        ascii_chars = sum(1 for char in text if ord(char) < 128)
        non_ascii = len(text) - ascii_chars
        return (
            ascii_chars / 5.0 + non_ascii * 0.85,
            ascii_chars / 4.0 + non_ascii * 1.00,
            ascii_chars / 3.2 + non_ascii * 1.20,
        )


@dataclass
class RequestMetrics:
    model_id: str
    premium_units: float
    tool_ids: list[str]
    input_direct: tuple[float, ...]
    input_prompt_replay: tuple[float, ...]
    input_hidden_tools: tuple[float, ...]
    input_request_overhead: tuple[float, ...]
    output_visible: tuple[float, ...]
    output_thinking: tuple[float, ...]
    output_edit: tuple[float, ...]

    def input_total(self) -> tuple[float, ...]:
        total = add_vectors(self.input_direct, self.input_prompt_replay)
        total = add_vectors(total, self.input_hidden_tools)
        total = add_vectors(total, self.input_request_overhead)
        return total

    def output_total(self) -> tuple[float, ...]:
        total = add_vectors(self.output_visible, self.output_thinking)
        total = add_vectors(total, self.output_edit)
        return total

    def grand_total(self) -> tuple[float, ...]:
        return add_vectors(self.input_total(), self.output_total())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate GitHub Copilot chat token usage for a project from VS Code "
            "workspaceStorage sessions and export detailed reports."
        )
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Absolute path to the project directory.",
    )
    parser.add_argument(
        "--workspace-storage-root",
        default=str(DEFAULT_WORKSPACE_STORAGE_ROOT),
        help="Root directory that contains VS Code workspaceStorage folders.",
    )
    parser.add_argument(
        "--workspace-folder",
        action="append",
        default=[],
        help=(
            "Specific workspaceStorage folder to scan. Repeatable. If omitted, "
            "all folders under --workspace-storage-root are scanned."
        ),
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Directory where report folders are created.",
    )
    parser.add_argument(
        "--timestamp",
        default=datetime.now().strftime("%Y%m%d-%H%M%S"),
        help="Timestamp label used in the output folder name.",
    )
    parser.add_argument(
        "--budget-profile",
        choices=("standard", "upper"),
        default="standard",
        help="Standard uses the existing 3-scenario estimate. Upper adds a budget_upper scenario.",
    )
    return parser.parse_args()


def normalize_project_path(project_arg: str) -> Path:
    project_path = Path(project_arg).expanduser().resolve()
    if not project_path.is_dir():
        raise SystemExit(f"Project path is not a directory: {project_path}")
    return project_path


def project_uri_prefix(project_path: Path) -> str:
    return project_path.as_uri().rstrip("/") + "/"


def iter_workspace_folders(root: Path, explicit_folders: list[str]) -> list[Path]:
    if explicit_folders:
        folders = [Path(item).expanduser().resolve() for item in explicit_folders]
        return [folder for folder in folders if folder.is_dir()]
    if not root.is_dir():
        raise SystemExit(f"workspaceStorage root not found: {root}")
    return sorted(path for path in root.iterdir() if path.is_dir())


def file_contains_string(path: Path, needles: tuple[str, ...]) -> bool:
    max_len = max(len(needle) for needle in needles)
    overlap = max_len - 1
    previous = ""
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return False
            combined = previous + chunk
            if any(needle in combined for needle in needles):
                return True
            previous = combined[-overlap:] if overlap > 0 else ""


def find_models_json_files(workspace_folder: Path) -> list[Path]:
    debug_logs = workspace_folder / "GitHub.copilot-chat" / "debug-logs"
    if not debug_logs.is_dir():
        return []
    return sorted(debug_logs.glob("*/models.json"))


def load_model_multipliers(workspace_folder: Path) -> dict[str, float]:
    multipliers: dict[str, float] = {}
    for models_path in find_models_json_files(workspace_folder):
        try:
            payload = json.loads(models_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            if not isinstance(item, dict):
                continue
            multiplier = float(((item.get("billing") or {}).get("multiplier")) or 1.0)
            for key in (
                item.get("id"),
                item.get("version"),
                f"copilot/{item.get('id')}" if item.get("id") else None,
                f"copilot/{item.get('version')}" if item.get("version") else None,
            ):
                if key:
                    multipliers[str(key)] = multiplier
    return multipliers


def load_session(path: Path) -> dict[str, Any] | None:
    if path.suffix == ".json":
        try:
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return None

    state: dict[str, Any] | None = None

    def ensure_path(root: dict[str, Any], path_parts: list[Any]) -> tuple[Any, Any]:
        current: Any = root
        for index, key in enumerate(path_parts[:-1]):
            next_key = path_parts[index + 1]
            if isinstance(key, int):
                while len(current) <= key:
                    current.append([] if isinstance(next_key, int) else {})
                current = current[key]
            else:
                if key not in current or current[key] is None:
                    current[key] = [] if isinstance(next_key, int) else {}
                current = current[key]
        return current, path_parts[-1]

    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                item = json.loads(line)
                kind = item.get("kind")
                if kind == 0:
                    state = item.get("v")
                elif kind == 1 and state is not None:
                    parent, last = ensure_path(state, item["k"])
                    if isinstance(last, int):
                        while len(parent) <= last:
                            parent.append(None)
                        parent[last] = item.get("v")
                    else:
                        parent[last] = item.get("v")
                elif kind == 2 and state is not None:
                    parent, last = ensure_path(state, item["k"])
                    if last not in parent or parent[last] is None:
                        parent[last] = []
                    parent[last].extend(item.get("v") or [])
    except Exception:
        return None
    return state


def default_hidden_tool_cost(tool_id: str) -> tuple[int, int, int]:
    if "browser" in tool_id:
        return (80, 200, 500)
    return (100, 200, 400)


def classify_file_kind(relative_path: Path) -> str | None:
    extension = relative_path.suffix.lower()
    path_text = relative_path.as_posix()
    if extension in CODE_EXTENSIONS:
        filename = relative_path.name.lower()
        if (
            "/tests/" in f"/{path_text}/"
            or filename.startswith("test_")
            or filename.endswith("_test.py")
            or ".spec." in filename
            or ".test." in filename
        ):
            return "tests"
        return "source"
    if extension in CONFIG_EXTENSIONS or relative_path.name in {"Dockerfile", ".env", ".env.example"}:
        return "config"
    if extension in DOC_EXTENSIONS:
        return "docs"
    return None


def should_skip_path(relative_path: Path) -> bool:
    if any(part in EXCLUDED_DIR_NAMES for part in relative_path.parts):
        return True
    relative_text = relative_path.as_posix()
    return any(relative_text.startswith(prefix) for prefix in EXCLUDED_RELATIVE_PREFIXES)


def count_loc(project_path: Path) -> dict[str, Any]:
    totals = {
        "source": {"files": 0, "lines": 0, "nonempty": 0, "effective": 0},
        "tests": {"files": 0, "lines": 0, "nonempty": 0, "effective": 0},
        "config": {"files": 0, "lines": 0, "nonempty": 0, "effective": 0},
        "docs": {"files": 0, "lines": 0, "nonempty": 0, "effective": 0},
    }
    by_extension: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"files": 0, "lines": 0, "nonempty": 0, "effective": 0}
    )

    for root, dirnames, filenames in os.walk(project_path):
        current_root = Path(root)
        relative_root = current_root.relative_to(project_path)
        dirnames[:] = [
            name
            for name in dirnames
            if not should_skip_path(relative_root / name)
        ]
        for filename in filenames:
            absolute_path = current_root / filename
            relative_path = absolute_path.relative_to(project_path)
            if should_skip_path(relative_path):
                continue
            kind = classify_file_kind(relative_path)
            if kind is None:
                continue
            extension = absolute_path.suffix.lower() or filename
            stats = {"lines": 0, "nonempty": 0, "effective": 0}
            prefixes = LINE_COMMENT_PREFIXES.get(absolute_path.suffix.lower(), ())
            try:
                with absolute_path.open("r", encoding="utf-8", errors="ignore") as handle:
                    for line in handle:
                        stats["lines"] += 1
                        stripped = line.strip()
                        if not stripped:
                            continue
                        stats["nonempty"] += 1
                        if prefixes and any(stripped.startswith(prefix) for prefix in prefixes):
                            continue
                        stats["effective"] += 1
            except Exception:
                continue
            totals[kind]["files"] += 1
            totals[kind]["lines"] += stats["lines"]
            totals[kind]["nonempty"] += stats["nonempty"]
            totals[kind]["effective"] += stats["effective"]
            extension_bucket = by_extension[(kind, extension)]
            extension_bucket["files"] += 1
            extension_bucket["lines"] += stats["lines"]
            extension_bucket["nonempty"] += stats["nonempty"]
            extension_bucket["effective"] += stats["effective"]

    totals["project"] = {
        "approx_code_lines": (
            totals["source"]["effective"]
            + totals["tests"]["effective"]
            + totals["config"]["effective"]
        ),
        "product_source_lines": totals["source"]["effective"],
        "tests_lines": totals["tests"]["effective"],
        "config_lines": totals["config"]["effective"],
        "docs_lines": totals["docs"]["effective"],
    }
    extension_rows = []
    for (kind, extension), stats in sorted(by_extension.items()):
        extension_rows.append(
            {
                "kind": kind,
                "extension": extension,
                **stats,
            }
        )
    return {"totals": totals, "by_extension": extension_rows}


def extract_request_parts(
    request: dict[str, Any],
    project_path: str,
    project_uri: str,
) -> dict[str, Any]:
    message = request.get("message") or {}
    user_text = message.get("text") if isinstance(message, dict) else str(message or "")
    blob_hit = project_path in user_text or project_uri in user_text
    visible_parts: list[str] = []
    thinking_parts: list[str] = []
    edit_parts: list[str] = []
    tool_ids: list[str] = []
    for item in request.get("response") or []:
        if not isinstance(item, dict):
            continue
        blob = json.dumps(item, ensure_ascii=False)
        if project_path in blob or project_uri in blob:
            blob_hit = True
        kind = item.get("kind")
        if kind is None and item.get("value"):
            visible_parts.append(str(item["value"]))
        elif kind == "thinking" and item.get("value"):
            thinking_parts.append(str(item["value"]))
        elif kind == "textEditGroup":
            for group in item.get("edits") or []:
                for edit in group or []:
                    if isinstance(edit, dict) and edit.get("text"):
                        edit_parts.append(str(edit["text"]))
        elif kind == "toolInvocationSerialized" and item.get("toolId"):
            tool_ids.append(str(item["toolId"]))
    return {
        "user_text": user_text,
        "visible_text": "\n".join(visible_parts),
        "thinking_text": "\n".join(thinking_parts),
        "edit_text": "\n".join(edit_parts),
        "tool_ids": tool_ids,
        "references_project": blob_hit,
    }


def first_relevant_request_index(
    requests: list[dict[str, Any]],
    project_path: str,
    project_uri: str,
) -> int | None:
    for index, request in enumerate(requests):
        if extract_request_parts(request, project_path, project_uri)["references_project"]:
            return index
    return None


def locate_relevant_sessions(
    workspace_folder: Path,
    project_path: str,
    project_uri: str,
) -> tuple[set[str], set[str]]:
    edit_session_ids: set[str] = set()
    chat_session_ids: set[str] = set()

    editing_root = workspace_folder / "chatEditingSessions"
    if editing_root.is_dir():
        for session_dir in editing_root.iterdir():
            state_path = session_dir / "state.json"
            if not state_path.is_file():
                continue
            try:
                if file_contains_string(state_path, (project_path, project_uri)):
                    edit_session_ids.add(session_dir.name)
            except Exception:
                continue

    chat_root = workspace_folder / "chatSessions"
    if chat_root.is_dir():
        for path in chat_root.glob("*.json*"):
            session_id = path.stem
            if session_id in edit_session_ids:
                chat_session_ids.add(session_id)
                continue
            try:
                if file_contains_string(path, (project_path, project_uri)):
                    chat_session_ids.add(session_id)
            except Exception:
                continue

    return edit_session_ids, chat_session_ids


def build_request_metrics(
    request: dict[str, Any],
    history_visible: list[str],
    estimator: TokenEstimator,
    project_path: str,
    project_uri: str,
    model_multipliers: dict[str, float],
    scenarios: tuple[str, ...],
    tool_hidden_costs: dict[str, tuple[int, ...]],
    request_overhead: tuple[int, ...],
) -> tuple[RequestMetrics, dict[str, Any]]:
    parts = extract_request_parts(request, project_path, project_uri)
    prompt_text = "\n".join(history_visible + ([parts["user_text"]] if parts["user_text"] else []))
    vector_size = len(scenarios)
    tool_cost = tuple(0.0 for _ in range(vector_size))
    tool_counter = Counter(parts["tool_ids"])
    for tool_id, count in tool_counter.items():
        tool_cost = add_vectors(
            tool_cost,
            scale_vector(
                broadcast_vector(tool_hidden_costs.get(tool_id, default_hidden_tool_cost(tool_id)), vector_size),
                count,
            ),
        )

    model_id = (
        request.get("modelId")
        or ((request.get("modelState") or {}).get("identifier"))
        or "unknown"
    )
    premium_units = float(
        model_multipliers.get(str(model_id), model_multipliers.get(str(model_id).replace("copilot/", ""), 1.0))
    )

    metrics = RequestMetrics(
        model_id=str(model_id),
        premium_units=premium_units,
        tool_ids=parts["tool_ids"],
        input_direct=broadcast_vector(estimator.estimate(parts["user_text"]), vector_size),
        input_prompt_replay=broadcast_vector(estimator.estimate(prompt_text), vector_size),
        input_hidden_tools=tool_cost,
        input_request_overhead=tuple(float(value) for value in request_overhead),
        output_visible=broadcast_vector(estimator.estimate(parts["visible_text"]), vector_size),
        output_thinking=broadcast_vector(estimator.estimate(parts["thinking_text"]), vector_size),
        output_edit=broadcast_vector(estimator.estimate(parts["edit_text"]), vector_size),
    )
    return metrics, parts


def scenario_value(value: tuple[float, ...], scenario: str, scenarios: tuple[str, ...]) -> int:
    return round(value[scenarios.index(scenario)])


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def analyze_project(project_path: Path, workspace_folders: list[Path], budget_profile: str) -> dict[str, Any]:
    estimator = TokenEstimator()
    project_path_text = str(project_path).rstrip("/") + "/"
    project_uri = project_uri_prefix(project_path)
    scenarios = get_scenarios(budget_profile)
    zero_vector = tuple(0.0 for _ in scenarios)
    tool_hidden_costs = build_tool_hidden_costs(budget_profile)
    request_overhead = build_request_overhead(budget_profile)

    session_rows: list[dict[str, Any]] = []
    session_model_buckets: dict[tuple[str, str], dict[str, Any]] = {}
    model_buckets: dict[str, dict[str, Any]] = {}
    tool_buckets: Counter[str] = Counter()

    summary = {
        "workspace_folders_scanned": [str(folder) for folder in workspace_folders],
        "token_estimator": estimator.mode,
        "budget_profile": budget_profile,
        "scenarios": list(scenarios),
        "sessions": 0,
        "requests": 0,
        "premium_units": 0.0,
        "input_direct": tuple(0.0 for _ in scenarios),
        "input_prompt_replay": tuple(0.0 for _ in scenarios),
        "input_hidden_tools": tuple(0.0 for _ in scenarios),
        "input_request_overhead": tuple(0.0 for _ in scenarios),
        "output_visible": tuple(0.0 for _ in scenarios),
        "output_thinking": tuple(0.0 for _ in scenarios),
        "output_edit": tuple(0.0 for _ in scenarios),
    }

    for workspace_folder in workspace_folders:
        model_multipliers = load_model_multipliers(workspace_folder)
        edit_session_ids, relevant_session_ids = locate_relevant_sessions(
            workspace_folder,
            project_path_text,
            project_uri,
        )
        chat_root = workspace_folder / "chatSessions"
        if not chat_root.is_dir():
            continue

        for session_id in sorted(relevant_session_ids):
            session_path_jsonl = chat_root / f"{session_id}.jsonl"
            session_path_json = chat_root / f"{session_id}.json"
            session_path = session_path_jsonl if session_path_jsonl.exists() else session_path_json
            if not session_path.exists():
                continue
            session = load_session(session_path)
            if not session:
                continue

            requests = session.get("requests") or []
            if not requests:
                continue

            start_index = first_relevant_request_index(requests, project_path_text, project_uri)
            if start_index is None:
                if session_id in edit_session_ids:
                    start_index = 0
                else:
                    continue

            session_requests = requests[start_index:]
            history_visible: list[str] = []
            session_totals = {
                "input_total": zero_vector,
                "output_total": zero_vector,
                "grand_total": zero_vector,
                "premium_units": 0.0,
                "models": Counter(),
                "tools": Counter(),
            }

            for request in session_requests:
                metrics, parts = build_request_metrics(
                    request,
                    history_visible,
                    estimator,
                    project_path_text,
                    project_uri,
                    model_multipliers,
                    scenarios,
                    tool_hidden_costs,
                    request_overhead,
                )

                input_total = metrics.input_total()
                output_total = metrics.output_total()
                grand_total = metrics.grand_total()

                summary["requests"] += 1
                summary["premium_units"] += metrics.premium_units
                for key, value in (
                    ("input_direct", metrics.input_direct),
                    ("input_prompt_replay", metrics.input_prompt_replay),
                    ("input_hidden_tools", metrics.input_hidden_tools),
                    ("input_request_overhead", metrics.input_request_overhead),
                    ("output_visible", metrics.output_visible),
                    ("output_thinking", metrics.output_thinking),
                    ("output_edit", metrics.output_edit),
                ):
                    summary[key] = add_vectors(summary[key], value)

                session_totals["input_total"] = add_vectors(session_totals["input_total"], input_total)
                session_totals["output_total"] = add_vectors(session_totals["output_total"], output_total)
                session_totals["grand_total"] = add_vectors(session_totals["grand_total"], grand_total)
                session_totals["premium_units"] += metrics.premium_units
                session_totals["models"][metrics.model_id] += 1
                session_totals["tools"].update(metrics.tool_ids)

                model_bucket = model_buckets.setdefault(
                    metrics.model_id,
                    {
                        "model_id": metrics.model_id,
                        "request_count": 0,
                        "premium_units": 0.0,
                        "input_total": zero_vector,
                        "output_total": zero_vector,
                        "grand_total": zero_vector,
                    },
                )
                model_bucket["request_count"] += 1
                model_bucket["premium_units"] += metrics.premium_units
                model_bucket["input_total"] = add_vectors(model_bucket["input_total"], input_total)
                model_bucket["output_total"] = add_vectors(model_bucket["output_total"], output_total)
                model_bucket["grand_total"] = add_vectors(model_bucket["grand_total"], grand_total)

                session_model_key = (session_id, metrics.model_id)
                session_model_bucket = session_model_buckets.setdefault(
                    session_model_key,
                    {
                        "workspace_folder": str(workspace_folder),
                        "session_id": session_id,
                        "session_title": session.get("customTitle") or "",
                        "model_id": metrics.model_id,
                        "request_count": 0,
                        "premium_units": 0.0,
                        "input_total": zero_vector,
                        "output_total": zero_vector,
                        "grand_total": zero_vector,
                    },
                )
                session_model_bucket["request_count"] += 1
                session_model_bucket["premium_units"] += metrics.premium_units
                session_model_bucket["input_total"] = add_vectors(session_model_bucket["input_total"], input_total)
                session_model_bucket["output_total"] = add_vectors(session_model_bucket["output_total"], output_total)
                session_model_bucket["grand_total"] = add_vectors(session_model_bucket["grand_total"], grand_total)

                tool_buckets.update(metrics.tool_ids)

                if parts["user_text"]:
                    history_visible.append("User: " + parts["user_text"])
                if parts["visible_text"]:
                    history_visible.append("Assistant: " + parts["visible_text"])

            summary["sessions"] += 1
            session_rows.append(
                {
                    "workspace_folder": str(workspace_folder),
                    "session_id": session_id,
                    "session_title": session.get("customTitle") or "",
                    "start_request_index": start_index,
                    "request_count": len(session_requests),
                    "premium_units": round(session_totals["premium_units"], 2),
                    "dominant_model": session_totals["models"].most_common(1)[0][0] if session_totals["models"] else "unknown",
                    "models_json": json.dumps(dict(session_totals["models"]), ensure_ascii=False),
                    "top_tools_json": json.dumps(session_totals["tools"].most_common(10), ensure_ascii=False),
                    **{
                        f"input_tokens_{scenario}": scenario_value(session_totals["input_total"], scenario, scenarios)
                        for scenario in scenarios
                    },
                    **{
                        f"output_tokens_{scenario}": scenario_value(session_totals["output_total"], scenario, scenarios)
                        for scenario in scenarios
                    },
                    **{
                        f"total_tokens_{scenario}": scenario_value(session_totals["grand_total"], scenario, scenarios)
                        for scenario in scenarios
                    },
                }
            )

    session_rows.sort(key=lambda row: row[f"total_tokens_{scenarios[-1] if budget_profile == 'upper' else 'main'}"], reverse=True)

    session_model_rows = []
    for bucket in session_model_buckets.values():
        session_model_rows.append(
            {
                "workspace_folder": bucket["workspace_folder"],
                "session_id": bucket["session_id"],
                "session_title": bucket["session_title"],
                "model_id": bucket["model_id"],
                "request_count": bucket["request_count"],
                "premium_units": round(bucket["premium_units"], 2),
                **{
                    f"input_tokens_{scenario}": scenario_value(bucket["input_total"], scenario, scenarios)
                    for scenario in scenarios
                },
                **{
                    f"output_tokens_{scenario}": scenario_value(bucket["output_total"], scenario, scenarios)
                    for scenario in scenarios
                },
                **{
                    f"total_tokens_{scenario}": scenario_value(bucket["grand_total"], scenario, scenarios)
                    for scenario in scenarios
                },
            }
        )
    session_model_rows.sort(key=lambda row: row[f"total_tokens_{scenarios[-1] if budget_profile == 'upper' else 'main'}"], reverse=True)

    model_rows = []
    for bucket in model_buckets.values():
        model_rows.append(
            {
                "model_id": bucket["model_id"],
                "request_count": bucket["request_count"],
                "premium_units": round(bucket["premium_units"], 2),
                **{
                    f"input_tokens_{scenario}": scenario_value(bucket["input_total"], scenario, scenarios)
                    for scenario in scenarios
                },
                **{
                    f"output_tokens_{scenario}": scenario_value(bucket["output_total"], scenario, scenarios)
                    for scenario in scenarios
                },
                **{
                    f"total_tokens_{scenario}": scenario_value(bucket["grand_total"], scenario, scenarios)
                    for scenario in scenarios
                },
            }
        )
    model_rows.sort(key=lambda row: row[f"total_tokens_{scenarios[-1] if budget_profile == 'upper' else 'main'}"], reverse=True)

    top_tools = []
    for tool_id, count in tool_buckets.most_common(50):
        hidden_costs = broadcast_vector(
            tool_hidden_costs.get(tool_id, default_hidden_tool_cost(tool_id)),
            len(scenarios),
        )
        top_tools.append(
            {
                "tool_id": tool_id,
                "count": count,
                **{
                    f"hidden_tokens_{scenario}": hidden_costs[index] * count
                    for index, scenario in enumerate(scenarios)
                },
            }
        )

    input_total = add_vectors(summary["input_direct"], summary["input_prompt_replay"])
    input_total = add_vectors(input_total, summary["input_hidden_tools"])
    input_total = add_vectors(input_total, summary["input_request_overhead"])
    output_total = add_vectors(summary["output_visible"], summary["output_thinking"])
    output_total = add_vectors(output_total, summary["output_edit"])
    grand_total = add_vectors(input_total, output_total)

    detail_sort_scenario = scenarios[-1] if budget_profile == "upper" else "main"

    summary_payload = {
        "project_path": str(project_path),
        "token_estimator": estimator.mode,
        "budget_profile": budget_profile,
        "workspace_folders_scanned": summary["workspace_folders_scanned"],
        "session_count": summary["sessions"],
        "request_count": summary["requests"],
        "premium_request_units": round(summary["premium_units"], 2),
        "scenario_labels": list(scenarios),
        "input_tokens": {
            "direct_user_text": vector_to_int_list(summary["input_direct"]),
            "prompt_replay": vector_to_int_list(summary["input_prompt_replay"]),
            "hidden_tool_results": vector_to_int_list(summary["input_hidden_tools"]),
            "copilot_request_overhead": vector_to_int_list(summary["input_request_overhead"]),
            "total": vector_to_int_list(input_total),
        },
        "output_tokens": {
            "visible_responses": vector_to_int_list(summary["output_visible"]),
            "thinking": vector_to_int_list(summary["output_thinking"]),
            "text_edits": vector_to_int_list(summary["output_edit"]),
            "total": vector_to_int_list(output_total),
        },
        "grand_total_tokens": vector_to_int_list(grand_total),
        "detail_sort_scenario": detail_sort_scenario,
    }

    return {
        "summary": summary_payload,
        "sessions": session_rows,
        "session_models": session_model_rows,
        "models": model_rows,
        "top_tools": top_tools,
    }


def export_reports(report_root: Path, analysis: dict[str, Any], loc_summary: dict[str, Any], budget_profile: str) -> None:
    report_root.mkdir(parents=True, exist_ok=True)
    write_json(report_root / "summary.json", analysis["summary"])
    write_json(report_root / "loc_summary.json", loc_summary)
    write_csv(report_root / "sessions.csv", analysis["sessions"])
    write_csv(report_root / "session_models.csv", analysis["session_models"])
    write_csv(report_root / "models.csv", analysis["models"])
    write_csv(report_root / "top_tools.csv", analysis["top_tools"])
    write_csv(report_root / "loc_by_extension.csv", loc_summary["by_extension"])


def main() -> None:
    args = parse_args()
    project_path = normalize_project_path(args.project)
    workspace_root = Path(args.workspace_storage_root).expanduser().resolve()
    workspace_folders = iter_workspace_folders(workspace_root, args.workspace_folder)
    if not workspace_folders:
        raise SystemExit("No workspaceStorage folders were found to scan.")

    analysis = analyze_project(project_path, workspace_folders, args.budget_profile)
    loc_summary = count_loc(project_path)

    report_folder_name = f"{safe_slug(project_path.name)}-{args.budget_profile}-{args.timestamp}"
    report_root = Path(args.out_dir).expanduser().resolve() / report_folder_name
    export_reports(report_root, analysis, loc_summary, args.budget_profile)

    printable = {
        "report_root": str(report_root),
        "summary": analysis["summary"],
        "loc": loc_summary["totals"]["project"],
        "session_report": str(report_root / "sessions.csv"),
        "session_model_report": str(report_root / "session_models.csv"),
        "model_report": str(report_root / "models.csv"),
        "tool_report": str(report_root / "top_tools.csv"),
        "loc_report": str(report_root / "loc_by_extension.csv"),
    }
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()