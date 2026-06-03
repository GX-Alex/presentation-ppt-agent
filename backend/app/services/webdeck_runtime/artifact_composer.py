"""
Deck Composer — 最终组装器 (对齐 high.md §5.3.5 Deck Integrator)。
负责将所有页面 HTML 组装成完整的 Web Deck。
生成: 路由、目录、主题、页面切换、进度条、URL 同步。
"""
import logging
import os
import re
from typing import Any

from app.models.tables import DeckPage
from app.services.webdeck_runtime.contracts import DeckManifest, DeckShellConfig

logger = logging.getLogger(__name__)

_ECHARTS_JS_URL = os.getenv("ECHARTS_JS_URL", "/vendor/echarts.min.js")

_ECHARTS_CDN_SCRIPT_RE = re.compile(
  r'<script[^>]+src=["\']https://cdn\.jsdelivr\.net/npm/echarts@5/dist/echarts\.min\.js["\'][^>]*>\s*</script>',
  flags=re.IGNORECASE,
)
_ECHARTS_INIT_SCRIPT_RE = re.compile(
  r'<script(?P<attrs>(?![^>]*\bsrc=)[^>]*)>(?P<body>[\s\S]*?echarts\.init\([\s\S]*?)</script>',
  flags=re.IGNORECASE,
)
_CHART_READY_WRAPPER_PATTERNS = [
  re.compile(
    r'^\s*document\.addEventListener\(\s*["\']DOMContentLoaded["\']\s*,\s*function\s*\([^)]*\)\s*\{(?P<body>[\s\S]*?)\}\s*\)\s*;?\s*$',
    flags=re.IGNORECASE,
  ),
  re.compile(
    r'^\s*(?:document|window)\.addEventListener\(\s*["\'](?:DOMContentLoaded|load)["\']\s*,\s*\(?[^)]*\)?\s*=>\s*\{(?P<body>[\s\S]*?)\}\s*\)\s*;?\s*$',
    flags=re.IGNORECASE,
  ),
  re.compile(
    r'^\s*window\.onload\s*=\s*function\s*\([^)]*\)\s*\{(?P<body>[\s\S]*?)\}\s*;?\s*$',
    flags=re.IGNORECASE,
  ),
]


class DeckComposer:
    """
    Deck 组装器 — 将 PageBundle 集合组合成最终可独立部署的 Web Deck。
    对齐 high.md §5.3.5: 路由 + 目录 + 主题 + 页面切换 + 进度条 + URL state。
    """

    @staticmethod
    def _normalize_chart_init_body(script_body: str) -> str:
      """展开 DOM ready / load 包装，保证延迟执行时 chart init 仍然真正运行。"""
      normalized = (script_body or "").strip()

      for _ in range(3):
        next_body = normalized
        for pattern in _CHART_READY_WRAPPER_PATTERNS:
          match = pattern.match(normalized)
          if match:
            next_body = (match.group("body") or "").strip()
            break
        if next_body == normalized:
          break
        normalized = next_body

      return normalized

    @staticmethod
    def _prepare_page_section(section_html: str) -> str:
      """规范化页面片段中的 ECharts 脚本，避免隐藏页提前初始化与重复加载 runtime。"""
      normalized = _ECHARTS_CDN_SCRIPT_RE.sub("", section_html)

      def _replace_chart_init(match: re.Match[str]) -> str:
        attrs = match.group("attrs") or ""
        body = DeckComposer._normalize_chart_init_body(match.group("body") or "")
        attrs = re.sub(r'\s+type=(["\']).*?\1', "", attrs, flags=re.IGNORECASE)
        return f'<script type="application/webdeck-chart-init"{attrs}>{body}</script>'

      return _ECHARTS_INIT_SCRIPT_RE.sub(_replace_chart_init, normalized)

    def compose(
        self,
        manifest: DeckManifest,
        pages: list[DeckPage],
        shell_config: DeckShellConfig | None = None,
    ) -> str:
        """
        组装完整的 Web Deck HTML。

        Args:
            manifest: DeckManifest
            pages: 所有页面记录（已排序）
            shell_config: Deck Shell 配置

        Returns:
            完整的单文件 HTML
        """
        config = shell_config or DeckShellConfig()
        theme = manifest.global_theme

        # 收集所有页面的 HTML
        page_sections = []
        for page in pages:
          if page.html:
            page_sections.append(self._prepare_page_section(page.html))
          else:
            # 还没有生成的页面用占位符
            page_sections.append(
              f'<section data-page-id="{page.page_id}" class="deck-page deck-page--empty">'
              f'<div style="display:flex;align-items:center;justify-content:center;'
              f'min-height:100vh;color:{theme.text_color};opacity:0.5;">'
              f'<p>{page.title or "加载中..."}</p></div></section>'
            )

        # 构建目录
        toc_items = []
        for i, page in enumerate(pages):
            toc_items.append(
                f'<li data-page-index="{i}" class="deck-toc-item" '
                f'onclick="goToPage({i})">{page.title or f"第 {i+1} 页"}</li>'
            )

        # 组装完整 HTML
        return self._build_full_html(
            title=manifest.title,
            subtitle=manifest.subtitle,
            theme=theme,
            config=config,
            page_sections=page_sections,
            toc_items=toc_items,
            total_pages=len(pages),
        )

    def _build_full_html(
        self,
        title: str,
        subtitle: str,
        theme,
        config: DeckShellConfig,
        page_sections: list[str],
        toc_items: list[str],
        total_pages: int,
    ) -> str:
        """构建完整的 Deck Shell HTML — P0 全屏翻页 + P1 组件库 + P2 缩放"""
        # P0: 每页包裹在 .deck-slide 中，第一页加 active 类
        slides_html_parts = []
        for i, section_html in enumerate(page_sections):
            active_class = " active" if i == 0 else ""
            slides_html_parts.append(
                f'<div class="deck-slide{active_class}">'
                f'<div class="deck-stage">'
                f'{section_html}'
                f'</div></div>'
            )
        slides_html = "\n".join(slides_html_parts)

        accent = theme.accent_color
        bg = theme.bg_color
        text_color = theme.text_color
        font_heading = theme.font_heading
        font_body = theme.font_body
        # 根据背景色亮暗计算 surface RGB（用于组件库自适应配色）
        # 亮色背景: surface = 黑色  暗色背景: surface = 白色
        try:
            _hex = bg.strip().lstrip("#")
            _r, _g, _b = int(_hex[0:2], 16), int(_hex[2:4], 16), int(_hex[4:6], 16)
            surface_rgb = "0, 0, 0" if (_r + _g + _b) > 382 else "255, 255, 255"
        except (ValueError, IndexError):
            surface_rgb = "255, 255, 255"

        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <!-- P1: Iconify 图标库 CDN -->
  <script src="https://code.iconify.design/iconify-icon/2.1.0/iconify-icon.min.js"></script>
  <script src="{_ECHARTS_JS_URL}"></script>
  <style>
    /* ── Reset ── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    html, body {{
      width: 100%; height: 100%;
      overflow: hidden;
      background: {bg};
      color: {text_color};
      font-family: {font_body};
    }}

    h1, h2, h3, h4, h5, h6 {{
      font-family: {font_heading};
    }}

    @page {{ size: 1280px 720px; margin: 0; }}

    /* ── P0: 全屏幻灯片容器 ── */
    #slides-container {{
      position: fixed;
      inset: 0;
    }}

    .deck-slide {{
      position: absolute;
      inset: 0;
      display: none;
      overflow: hidden;
    }}

    .deck-slide.active {{ display: block; }}

    /* P2: 内容画布 — 固定 1280×720，通过 JS scale+translate 适配视口 */
    .deck-stage {{
      width: 1280px;
      height: 720px;
      position: absolute;
      top: 0; left: 0;
      transform-origin: 0 0;
      overflow: hidden;
    }}

    .deck-stage > *,
    .deck-stage > section,
    .deck-stage > [data-page-id] {{
      width: 100% !important;
      height: 100% !important;
      max-height: 100% !important;
      min-height: 0 !important;
      overflow: hidden !important;
      box-sizing: border-box !important;
    }}

    /* ── 顶部进度条 ── */
    #deck-progress {{
      position: fixed; top: 0; left: 0; right: 0;
      height: 3px;
      background: rgba(var(--s-surface-rgb), 0.08);
      z-index: 1000;
    }}
    #deck-progress-bar {{
      height: 100%;
      background: {accent};
      transition: width 0.3s ease;
      width: 0%;
    }}

    /* ── P0: 右下角幽灵导航覆层 ── */
    #deck-nav-overlay {{
      position: fixed;
      bottom: 24px; right: 24px;
      display: flex;
      align-items: center;
      gap: 8px;
      z-index: 1000;
      opacity: 0.25;
      transition: opacity 0.2s;
    }}
    #deck-nav-overlay:hover {{ opacity: 1; }}

    .deck-nav-btn {{
      display: flex; align-items: center; justify-content: center;
      width: 36px; height: 36px;
      border-radius: 50%;
      border: 1px solid rgba(255,255,255,0.25);
      background: rgba(0,0,0,0.55);
      color: rgba(255,255,255,0.85);
      cursor: pointer;
      transition: all 0.15s;
      backdrop-filter: blur(8px);
      font-size: 18px;
    }}
    .deck-nav-btn:hover {{ background: rgba(255,255,255,0.15); color: white; }}
    .deck-nav-btn:disabled {{ opacity: 0.3; cursor: not-allowed; }}

    #deck-page-indicator {{
      font-size: 11px;
      color: rgba(255,255,255,0.65);
      min-width: 40px;
      text-align: center;
      font-family: {font_body};
    }}

    /* ── P1: CSS 变量 ── */
    :root {{
      --accent: {accent};
      --bg: {bg};
      --text: {text_color};
      --s-surface-rgb: {surface_rgb};
      --s-card-bg: rgba(var(--s-surface-rgb), 0.04);
      --s-card-border: rgba(var(--s-surface-rgb), 0.12);
      --s-radius: 12px;
    }}

    /* ── P1: shadcn/ui 风格全局组件类 (.s- 前缀) ── */
    .s-card {{
      background: var(--s-card-bg);
      border: 1px solid var(--s-card-border);
      border-radius: var(--s-radius);
      padding: 1rem 1.25rem;
    }}
    .s-card-hover {{ transition: all 0.2s; }}
    .s-card-hover:hover {{ background: rgba(var(--s-surface-rgb), 0.08); transform: translateY(-2px); }}
    .s-grid-2 {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; }}
    .s-grid-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }}
    .s-grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; }}
    .s-flex {{ display: flex; align-items: center; gap: 0.75rem; }}
    .s-flex-col {{ display: flex; flex-direction: column; gap: 0.75rem; }}
    .s-alert {{
      border-left: 4px solid var(--accent);
      background: rgba(var(--s-surface-rgb), 0.05);
      border-radius: 0 var(--s-radius) var(--s-radius) 0;
      padding: 0.75rem 1rem;
    }}
    .s-alert-warn {{ border-color: #f59e0b; background: rgba(245,158,11,0.08); }}
    .s-alert-error {{ border-color: #ef4444; background: rgba(239,68,68,0.08); }}
    .s-alert-success {{ border-color: #22c55e; background: rgba(34,197,94,0.08); }}
    .s-badge {{
      display: inline-flex; align-items: center;
      padding: 2px 10px; border-radius: 999px;
      font-size: 0.75rem; font-weight: 600;
      background: rgba(var(--s-surface-rgb), 0.08);
      color: var(--accent);
      border: 1px solid rgba(var(--s-surface-rgb), 0.2);
    }}
    .s-code {{
      font-family: "JetBrains Mono","Fira Code",monospace;
      background: rgba(var(--s-surface-rgb), 0.06);
      border: 1px solid rgba(var(--s-surface-rgb), 0.12);
      border-radius: 6px;
      padding: 0.2em 0.5em;
      font-size: 0.85em;
    }}
    .s-stat {{ text-align: center; }}
    .s-stat-value {{ font-size: 2.5rem; font-weight: 800; color: var(--accent); line-height: 1; }}
    .s-stat-label {{ font-size: 0.8rem; color: rgba(var(--s-surface-rgb), 0.55); margin-top: 0.25rem; }}
    .s-table {{ width: 100%; border-collapse: collapse; }}
    .s-table th {{ font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: rgba(var(--s-surface-rgb), 0.55); border-bottom: 1px solid rgba(var(--s-surface-rgb), 0.15); padding: 0.5rem 0.75rem; text-align: left; }}
    .s-table td {{ padding: 0.5rem 0.75rem; border-bottom: 1px solid rgba(var(--s-surface-rgb), 0.08); font-size: 0.875rem; }}
    .s-table tr:last-child td {{ border-bottom: none; }}
    .s-divider {{ height: 1px; background: rgba(var(--s-surface-rgb), 0.12); margin: 0.75rem 0; }}
    iconify-icon {{ display: inline-block; vertical-align: middle; }}

    /* ── 打印：每页独立输出 ── */
    @media print {{
      #deck-nav-overlay, #deck-progress {{ display: none !important; }}
      html, body {{ overflow: visible !important; background: {bg} !important; }}
      #slides-container {{ position: static !important; }}
      .deck-slide {{
        display: block !important;
        position: static !important;
        page-break-after: always;
        break-after: page;
        width: 100vw !important;
        height: 56.25vw !important;
      }}
      .deck-slide:last-child {{ page-break-after: auto; break-after: auto; }}
      .deck-stage {{
        transform: none !important;
        width: 100% !important;
        height: 100% !important;
      }}
    }}
  </style>
</head>
<body>
  <!-- 顶部进度条 -->
  <div id="deck-progress"><div id="deck-progress-bar"></div></div>

  <!-- P0: 幻灯片容器 -->
  <div id="slides-container">
{slides_html}
  </div>

  <!-- P0: 右下角幽灵导航 -->
  <div id="deck-nav-overlay">
    <button class="deck-nav-btn" id="prevBtn" onclick="prevPage()" aria-label="上一页" title="上一页 (←)">
      <iconify-icon icon="mdi:chevron-left"></iconify-icon>
    </button>
    <span id="deck-page-indicator">1 / {total_pages}</span>
    <button class="deck-nav-btn" id="nextBtn" onclick="nextPage()" aria-label="下一页" title="下一页 (→)">
      <iconify-icon icon="mdi:chevron-right"></iconify-icon>
    </button>
  </div>

  <script>
    // ── Web Deck Runtime (P0 + P2) ──
    var totalPages = {total_pages};
    var currentPage = 0;
    var slides = document.querySelectorAll('.deck-slide');

    // P2: 缩放并居中 .deck-stage 以适配视口
    function scaleSlide(slide) {{
      var stage = slide.querySelector('.deck-stage');
      if (!stage) return;
      var vw = slide.offsetWidth || window.innerWidth;
      var vh = slide.offsetHeight || window.innerHeight;
      var scale = Math.min(vw / 1280, vh / 720);
      var ox = (vw - 1280 * scale) / 2;
      var oy = (vh - 720 * scale) / 2;
      stage.style.transform = 'translate(' + ox + 'px, ' + oy + 'px) scale(' + scale + ')';
    }}

    function runChartInitScripts(slide) {{
      if (!slide || typeof window.echarts === 'undefined') return;
      slide.querySelectorAll('script[type="application/webdeck-chart-init"]:not([data-webdeck-executed="true"])').forEach(function(script) {{
        try {{
          var run = new Function(script.textContent || '');
          run();
          script.setAttribute('data-webdeck-executed', 'true');
        }} catch (error) {{
          console.warn('[WebDeck] chart init failed', error);
        }}
      }});
    }}

    function refreshActiveCharts() {{
      var activeSlide = slides[currentPage];
      if (!activeSlide || !window.echarts || typeof window.echarts.getInstanceByDom !== 'function') return;

      var nodes = activeSlide.querySelectorAll('[_echarts_instance_], .deck-chart-wrapper [id], [data-asset-kind="chart"][id]');
      var visited = new Set();
      nodes.forEach(function(node) {{
        if (visited.has(node)) return;
        visited.add(node);
        try {{
          var instance = window.echarts.getInstanceByDom(node);
          if (instance) {{
            instance.resize({{ animation: false }});
          }}
        }} catch (error) {{
          console.warn('[WebDeck] chart refresh failed', error);
        }}
      }});
    }}

    function syncActiveSlide() {{
      if (!slides[currentPage]) return;
      scaleSlide(slides[currentPage]);
      runChartInitScripts(slides[currentPage]);
      refreshActiveCharts();
      requestAnimationFrame(refreshActiveCharts);
      window.setTimeout(refreshActiveCharts, 120);
    }}

    function goToPage(index) {{
      if (index < 0 || index >= totalPages) return;
      slides[currentPage].classList.remove('active');
      currentPage = index;
      slides[currentPage].classList.add('active');
      syncActiveSlide();
      updateUI();
    }}

    function nextPage() {{ goToPage(currentPage + 1); }}
    function prevPage() {{ goToPage(currentPage - 1); }}

    function updateUI() {{
      document.getElementById('deck-progress-bar').style.width = ((currentPage + 1) / totalPages * 100) + '%';
      document.getElementById('deck-page-indicator').textContent = (currentPage + 1) + ' / ' + totalPages;
      document.getElementById('prevBtn').disabled = currentPage === 0;
      document.getElementById('nextBtn').disabled = currentPage === totalPages - 1;
    }}

    // P0: 左右方向键 + 空格键导航
    document.addEventListener('keydown', function(e) {{
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === ' ') {{
        e.preventDefault(); nextPage();
      }} else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {{
        e.preventDefault(); prevPage();
      }}
    }});

    // 初始化
    window.addEventListener('load', function() {{ syncActiveSlide(); updateUI(); }});
    window.addEventListener('resize', syncActiveSlide);
    // 两步初始化：立即尝试 + RAF 推迟确保布局完成后再缩放/刷新图表
    syncActiveSlide();
    requestAnimationFrame(function() {{ syncActiveSlide(); }});
    updateUI();
  </script>
</body>
</html>'''
