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
from html import escape as html_escape
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

from app.services.export_service import BACKEND_ROOT, EXPORT_DIR
from app.services.webdeck_runtime.pptx_native.fontawesome_subset import FA_SOLID_ICONS
from app.services.webdeck_runtime.pptx_native.svg_to_pptx import create_pptx_with_native_svg

logger = logging.getLogger(__name__)

PPTX_NATIVE_DIR = Path(__file__).resolve().parent / "pptx_native"
HTML_TO_SVG_SCRIPT = PPTX_NATIVE_DIR / "html_dom_to_editable_svg.js"
WORK_DIR = BACKEND_ROOT / "data" / "tmp" / "webdeck_native_pptx"
WORK_DIR.mkdir(parents=True, exist_ok=True)

FONTAWESOME_INLINE_STYLE = """
<style id="webdeck-fontawesome-inline-svg">
  .fa-inline-svg {
    display: inline-block !important;
    width: 1em !important;
    height: 1em !important;
    vertical-align: -0.125em !important;
    color: inherit;
    fill: currentColor;
    flex: none !important;
  }
  .fa-inline-svg path {
    fill: currentColor;
  }
</style>
"""


def _safe_title(title: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]", "_", title or "Web Deck")
    return cleaned[:50] or "Web_Deck"


def _fontawesome_icon_name(classes: str) -> str | None:
    ignored = {
        "fa",
        "fas",
        "far",
        "fab",
        "fal",
        "fad",
        "fa-solid",
        "fa-regular",
        "fa-brands",
        "fa-fw",
        "fa-lg",
        "fa-xs",
        "fa-sm",
        "fa-1x",
        "fa-2x",
        "fa-3x",
        "fa-4x",
        "fa-5x",
        "fa-6x",
        "fa-7x",
        "fa-8x",
        "fa-9x",
        "fa-10x",
    }
    for cls in classes.split():
        if cls.startswith("fa-") and cls not in ignored:
            return cls.removeprefix("fa-")
    return None


def _inline_fontawesome_icons(html: str) -> tuple[str, int]:
    """Convert Font Awesome <i> icons into inline SVG paths before browser layout."""
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        attrs = match.group(1)
        class_match = re.search(
            r'\bclass\s*=\s*(["\'])(.*?)\1',
            attrs,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not class_match:
            return match.group(0)
        classes = class_match.group(2)
        icon_name = _fontawesome_icon_name(classes)
        icon = FA_SOLID_ICONS.get(icon_name or "")
        if not icon:
            return match.group(0)

        style_match = re.search(
            r'\bstyle\s*=\s*(["\'])(.*?)\1',
            attrs,
            flags=re.IGNORECASE | re.DOTALL,
        )
        style = style_match.group(2) if style_match else ""
        width, height, path_data = icon
        count += 1
        return (
            f'<svg class="fa-inline-svg {html_escape(classes, quote=True)}" '
            f'viewBox="0 0 {width} {height}" aria-hidden="true" focusable="false" '
            f'style="{html_escape(style, quote=True)};overflow:visible;">'
            f'<path fill="currentColor" d="{html_escape(path_data, quote=True)}"></path>'
            f"</svg>"
        )

    next_html = re.sub(r"<i\b([^>]*)>\s*</i>", repl, html, flags=re.IGNORECASE | re.DOTALL)
    if count:
        next_html = re.sub(
            r"<link\b[^>]*(?:font-awesome|fontawesome)[^>]*>",
            "",
            next_html,
            flags=re.IGNORECASE,
        )
        next_html = re.sub(
            r"</head\s*>",
            FONTAWESOME_INLINE_STYLE + "\n</head>",
            next_html,
            count=1,
            flags=re.IGNORECASE,
        )
    return next_html, count


# Matches external <script src="..."> tags pointing to CDN domains.
# These block HTML parsing in headless Chrome and cause the export to hang
# when the CDN is unreachable. ECharts CDN scripts are converted to async
# (not removed) so the export script's waitForEchartsIfNeeded() can still
# capture charts. All other CDN scripts are removed.
_CDN_SCRIPT_RE = re.compile(
    r'<script\s[^>]*src=["\']https?://[^"\']*["\'][^>]*>\s*</script>',
    re.IGNORECASE,
)

# Injected immediately before the ECharts CDN <script async> tag.
# Uses Object.defineProperty to intercept window.echarts = ... the instant
# ECharts assigns itself, patching echarts.init to force SVG renderer before
# any code (including the webdeck's own runtime) can call echarts.init with
# the default canvas renderer.  Without this, fast CDN loads let the webdeck
# runtime create canvas instances first; the export script's later patch has
# no effect on already-created instances, causing intermittent blank charts.
# NOTE: __webdeckSvgPatched is also checked by forceEchartsSvgRenderer() in
# html_dom_to_editable_svg.js — keep the flag name in sync across both files.
_ECHARTS_SVG_PATCHER = (
    '<script>(function(){try{'
    'var _e;'
    'Object.defineProperty(window,"echarts",{'
    'get:function(){return _e;},'
    'set:function(v){'
    '_e=v;'
    'if(v&&v.init&&!v.__webdeckSvgPatched){'
    'var o=v.init.bind(v);'
    'v.init=function(d,t,p){return o(d,t,Object.assign({},p||{},{renderer:"svg"}));};'
    'v.__webdeckSvgPatched=true;'
    '}'
    '},'
    'configurable:true'
    '});'
    '}catch(e){}})();</script>'
)


def _handle_cdn_script(m: re.Match) -> str:
    """Prepend SVG patcher + convert ECharts CDN to async; strip all other CDN scripts."""
    src_match = re.search(r'src=["\']([^"\']*)["\']', m.group(0), re.IGNORECASE)
    if src_match and "echarts" in src_match.group(1).lower():
        tag = m.group(0)
        if not re.search(r'\basync\b', tag, re.IGNORECASE):
            tag = re.sub(r'<script\b', '<script async', tag, count=1, flags=re.IGNORECASE)
        return _ECHARTS_SVG_PATCHER + tag
    return ""


def _strip_blocking_scripts(html: str) -> str:
    """Remove/async-ify external CDN scripts before PPTX export.

    Non-ECharts <script src="https://..."> in <head> block Chrome parsing when
    the CDN is unreachable (20-second poll timeout). ECharts CDN scripts are
    converted to async (non-blocking) and preceded by an SVG renderer patcher
    that intercepts window.echarts assignment via Object.defineProperty, ensuring
    every echarts.init call uses SVG renderer regardless of which code runs first.

    webdeck-chart-init inline scripts are intentionally preserved — their
    non-standard type makes Chrome treat them as inert data (non-blocking),
    and the export script needs to execute them to initialise ECharts instances.
    """
    return _CDN_SCRIPT_RE.sub(_handle_cdn_script, html)


def _prepare_native_export_html(full_html: str) -> str:
    html = _strip_blocking_scripts(full_html)
    html, icon_count = _inline_fontawesome_icons(html)
    if icon_count:
        logger.info("[WebDeck] inlined %d Font Awesome icons for native PPTX export", icon_count)
    return html


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
    html_path.write_text(_prepare_native_export_html(full_html), encoding="utf-8")

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
