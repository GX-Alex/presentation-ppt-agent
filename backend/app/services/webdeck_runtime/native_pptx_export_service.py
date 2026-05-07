"""Native editable PPTX export for WebDeck.

Pipeline:
1. Persist the published WebDeck HTML to a temporary file.
2. Use Chrome/CDP via ``html_dom_to_editable_svg.js`` to extract editable SVG
   primitives from the rendered DOM.
3. Use the vendored ppt-master ``svg_to_pptx`` converter in native DrawingML
   mode so PowerPoint receives editable shapes/text instead of slide images.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

from app.services.export_service import BACKEND_ROOT, EXPORT_DIR
from app.services.webdeck_runtime.pptx_native.svg_to_pptx import create_pptx_with_native_svg

logger = logging.getLogger(__name__)

PPTX_NATIVE_DIR = Path(__file__).resolve().parent / "pptx_native"
HTML_TO_SVG_SCRIPT = PPTX_NATIVE_DIR / "html_dom_to_editable_svg.js"
WORK_DIR = BACKEND_ROOT / "data" / "tmp" / "webdeck_native_pptx"
WORK_DIR.mkdir(parents=True, exist_ok=True)


def _safe_title(title: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]", "_", title or "Web Deck")
    return cleaned[:50] or "Web_Deck"


async def export_webdeck_native_pptx(full_html: str, title: str) -> str:
    """Export a full WebDeck HTML document as native editable PPTX.

    Returns a static relative path like ``exports/foo_native.pptx``.
    """
    if not full_html.strip():
        raise ValueError("full_html cannot be empty")

    safe_title = _safe_title(title)
    run_id = uuid.uuid4().hex[:10]
    run_dir = WORK_DIR / f"{safe_title}_{run_id}"
    html_path = run_dir / "source.html"
    project_dir = run_dir / "pptmaster_project"
    output_filename = f"{safe_title}_{run_id}_native.pptx"
    output_path = EXPORT_DIR / output_filename

    run_dir.mkdir(parents=True, exist_ok=True)
    html_path.write_text(full_html, encoding="utf-8")

    try:
        await _run_html_to_svg(html_path=html_path, project_dir=project_dir)
        svg_files = sorted((project_dir / "svg_output").glob("*.svg"))
        if not svg_files:
            raise RuntimeError("HTML to SVG conversion produced no SVG slides")

        notes = _read_notes(project_dir / "notes")
        ok = await asyncio.to_thread(
            create_pptx_with_native_svg,
            svg_files,
            output_path,
            "ppt169",
            False,
            None,
            0.4,
            None,
            False,
            notes,
            True,
            True,
            None,
        )
        if not ok or not output_path.exists():
            raise RuntimeError("svg_to_pptx native conversion failed")

        logger.info(
            "[WebDeck] native PPTX export complete: %s (%d slides)",
            output_path,
            len(svg_files),
        )
        return f"exports/{output_filename}"
    finally:
        try:
            shutil.rmtree(run_dir)
        except OSError:
            logger.warning("[WebDeck] failed to remove native PPTX temp dir: %s", run_dir)


async def _run_html_to_svg(html_path: Path, project_dir: Path) -> None:
    env = await _build_node_export_env()
    proc = await asyncio.create_subprocess_exec(
        "node",
        str(HTML_TO_SVG_SCRIPT),
        str(html_path),
        str(project_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(
            "[WebDeck] html_dom_to_editable_svg failed (%s)\nstdout=%s\nstderr=%s",
            proc.returncode,
            stdout.decode("utf-8", errors="replace")[-4000:],
            stderr.decode("utf-8", errors="replace")[-4000:],
        )
        raise RuntimeError("HTML DOM to editable SVG conversion failed")


async def _build_node_export_env() -> dict[str, str]:
    env = dict(os.environ)
    if env.get("CHROME"):
        return env
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            executable_path = playwright.chromium.executable_path
        if executable_path:
            env["CHROME"] = executable_path
    except Exception as exc:  # pragma: no cover - best-effort runtime fallback
        logger.debug("[WebDeck] could not resolve Playwright Chromium path: %s", exc)
    return env


def _read_notes(notes_dir: Path) -> dict[str, str]:
    if not notes_dir.exists():
        return {}
    notes: dict[str, str] = {}
    for item in notes_dir.glob("*.md"):
        if item.name == "total.md":
            continue
        notes[item.stem] = item.read_text(encoding="utf-8", errors="replace")
    return notes
