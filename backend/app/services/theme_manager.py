"""
主题管理器 — 提供 PPT 内置主题定义。
三个内置主题: tech_dark（科技暗色）、business_light（商务浅色）、academic（学术风）。
每个主题包含 CSS 变量和 reveal.js 配置。
"""
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_REVEAL_JS_BASE = os.getenv("REVEAL_JS_BASE_URL", "/vendor/reveal.js")

# ──────────────── 内置主题定义 ────────────────

THEMES: dict[str, dict[str, Any]] = {
    "tech_dark": {
        "id": "tech_dark",
        "name": "科技暗色",
        "description": "深色背景 + 蓝色强调，适合技术分享和产品发布",
        "css": {
            "backgroundColor": "#0f172a",
            "color": "#e2e8f0",
            "headingColor": "#38bdf8",
            "accentColor": "#818cf8",
            "linkColor": "#38bdf8",
            "fontFamily": "'Inter', 'Noto Sans SC', sans-serif",
            "headingFontFamily": "'Inter', 'Noto Sans SC', sans-serif",
            "codeFontFamily": "'Fira Code', 'JetBrains Mono', monospace",
        },
        "reveal_config": {
            "transition": "slide",
            "backgroundTransition": "fade",
        },
        "slide_css": """
            .reveal section { text-align: left; }
            .reveal h1, .reveal h2 { color: #38bdf8; font-weight: 700; }
            .reveal h3 { color: #818cf8; font-weight: 600; }
            .reveal ul { list-style: none; padding-left: 0; }
            .reveal ul li { padding: 8px 0; padding-left: 24px; position: relative; }
            .reveal ul li::before { content: '▸'; position: absolute; left: 0; color: #38bdf8; }
            .reveal code { background: #1e293b; padding: 2px 8px; border-radius: 4px; font-size: 0.85em; }
            .reveal blockquote { border-left: 4px solid #38bdf8; padding-left: 16px; color: #94a3b8; }
            .reveal .slide-number { color: #475569; }
        """,
    },
    "business_light": {
        "id": "business_light",
        "name": "商务浅色",
        "description": "白色背景 + 蓝灰色调，适合商业报告和方案展示",
        "css": {
            "backgroundColor": "#ffffff",
            "color": "#1e293b",
            "headingColor": "#1e40af",
            "accentColor": "#2563eb",
            "linkColor": "#2563eb",
            "fontFamily": "'Inter', 'Noto Sans SC', sans-serif",
            "headingFontFamily": "'Inter', 'Noto Sans SC', sans-serif",
            "codeFontFamily": "'Fira Code', monospace",
        },
        "reveal_config": {
            "transition": "convex",
            "backgroundTransition": "slide",
        },
        "slide_css": """
            .reveal section { text-align: left; }
            .reveal h1, .reveal h2 { color: #1e40af; font-weight: 700; border-bottom: 3px solid #dbeafe; padding-bottom: 12px; }
            .reveal h3 { color: #2563eb; font-weight: 600; }
            .reveal ul li { padding: 6px 0; }
            .reveal code { background: #f1f5f9; padding: 2px 8px; border-radius: 4px; color: #1e40af; font-size: 0.85em; }
            .reveal blockquote { border-left: 4px solid #2563eb; padding-left: 16px; color: #64748b; background: #f8fafc; padding: 12px 16px; }
            .reveal table { width: 100%; border-collapse: collapse; }
            .reveal table th { background: #1e40af; color: white; padding: 8px 12px; }
            .reveal table td { border: 1px solid #e2e8f0; padding: 8px 12px; }
        """,
    },
    "academic": {
        "id": "academic",
        "name": "学术风",
        "description": "米白背景 + 深色文字，适合学术报告和论文答辩",
        "css": {
            "backgroundColor": "#fefce8",
            "color": "#1c1917",
            "headingColor": "#78350f",
            "accentColor": "#b45309",
            "linkColor": "#b45309",
            "fontFamily": "'Georgia', 'Noto Serif SC', serif",
            "headingFontFamily": "'Georgia', 'Noto Serif SC', serif",
            "codeFontFamily": "'Fira Code', monospace",
        },
        "reveal_config": {
            "transition": "fade",
            "backgroundTransition": "none",
        },
        "slide_css": """
            .reveal section { text-align: left; }
            .reveal h1, .reveal h2 { color: #78350f; font-weight: 700; font-style: normal; }
            .reveal h3 { color: #92400e; font-weight: 600; }
            .reveal ul li { padding: 4px 0; line-height: 1.8; }
            .reveal code { background: #fef3c7; padding: 2px 8px; border-radius: 3px; font-size: 0.85em; }
            .reveal blockquote { border-left: 3px solid #b45309; padding-left: 16px; color: #78350f; font-style: italic; }
            .reveal .references { font-size: 0.7em; color: #78350f; }
            .reveal sup { color: #b45309; font-weight: 600; }
        """,
    },
    "midnight_executive": {
        "id": "midnight_executive",
        "name": "午夜行政",
        "description": "深蓝背景 + 冰蓝高亮，适合高管汇报和战略规划",
        "css": {
            "backgroundColor": "#1E2761",
            "color": "#CADCFC",
            "headingColor": "#FFFFFF",
            "accentColor": "#7EC8E3",
            "linkColor": "#7EC8E3",
            "fontFamily": "'Inter', 'Noto Sans SC', sans-serif",
            "headingFontFamily": "'Inter', 'Noto Sans SC', sans-serif",
            "codeFontFamily": "'Fira Code', monospace",
        },
        "reveal_config": {
            "transition": "fade",
            "backgroundTransition": "fade",
        },
        "slide_css": """
            .reveal section { text-align: left; }
            .reveal h1, .reveal h2 { color: #FFFFFF; font-weight: 700; }
            .reveal h3 { color: #7EC8E3; font-weight: 600; }
            .reveal ul { list-style: none; padding-left: 0; }
            .reveal ul li { padding: 8px 0; padding-left: 24px; position: relative; }
            .reveal ul li::before { content: '▸'; position: absolute; left: 0; color: #7EC8E3; }
            .reveal code { background: #2a3a7a; padding: 2px 8px; border-radius: 4px; font-size: 0.85em; }
            .reveal blockquote { border-left: 4px solid #7EC8E3; padding-left: 16px; color: #8899cc; }
        """,
    },
    "forest_nature": {
        "id": "forest_nature",
        "name": "森林自然",
        "description": "深绿背景 + 苔绿高亮，适合环保、农业、可持续发展主题",
        "css": {
            "backgroundColor": "#1a3c2a",
            "color": "#d4e8d0",
            "headingColor": "#97BC62",
            "accentColor": "#4CAF50",
            "linkColor": "#97BC62",
            "fontFamily": "'Georgia', 'Noto Serif SC', serif",
            "headingFontFamily": "'Georgia', 'Noto Serif SC', serif",
            "codeFontFamily": "'Fira Code', monospace",
        },
        "reveal_config": {
            "transition": "slide",
            "backgroundTransition": "fade",
        },
        "slide_css": """
            .reveal section { text-align: left; }
            .reveal h1, .reveal h2 { color: #97BC62; font-weight: 700; }
            .reveal h3 { color: #4CAF50; font-weight: 600; }
            .reveal ul { list-style: none; padding-left: 0; }
            .reveal ul li { padding: 6px 0; padding-left: 24px; position: relative; }
            .reveal ul li::before { content: '🌿'; position: absolute; left: 0; font-size: 0.8em; }
            .reveal blockquote { border-left: 4px solid #4CAF50; padding-left: 16px; color: #8cb888; }
        """,
    },
    "coral_energy": {
        "id": "coral_energy",
        "name": "珊瑚活力",
        "description": "白色背景 + 珊瑚/金色强调，适合创意营销和品牌推广",
        "css": {
            "backgroundColor": "#FFFFFF",
            "color": "#2F3C7E",
            "headingColor": "#F96167",
            "accentColor": "#F9E795",
            "linkColor": "#F96167",
            "fontFamily": "'Inter', 'Noto Sans SC', sans-serif",
            "headingFontFamily": "'Inter', 'Noto Sans SC', sans-serif",
            "codeFontFamily": "'Fira Code', monospace",
        },
        "reveal_config": {
            "transition": "convex",
            "backgroundTransition": "slide",
        },
        "slide_css": """
            .reveal section { text-align: left; }
            .reveal h1, .reveal h2 { color: #F96167; font-weight: 700; }
            .reveal h3 { color: #2F3C7E; font-weight: 600; }
            .reveal ul li { padding: 6px 0; }
            .reveal blockquote { border-left: 4px solid #F96167; padding-left: 16px; color: #666; background: #FFF5F5; padding: 12px 16px; }
            .reveal table th { background: #F96167; color: white; padding: 8px 12px; }
            .reveal table td { border: 1px solid #F9E795; padding: 8px 12px; }
        """,
    },
    "charcoal_minimal": {
        "id": "charcoal_minimal",
        "name": "炭灰极简",
        "description": "炭灰+灰白极简风格，适合设计、建筑、艺术类展示",
        "css": {
            "backgroundColor": "#36454F",
            "color": "#F2F2F2",
            "headingColor": "#FFFFFF",
            "accentColor": "#E0E0E0",
            "linkColor": "#E0E0E0",
            "fontFamily": "'Inter', 'Noto Sans SC', sans-serif",
            "headingFontFamily": "'Inter', 'Noto Sans SC', sans-serif",
            "codeFontFamily": "'Fira Code', monospace",
        },
        "reveal_config": {
            "transition": "fade",
            "backgroundTransition": "fade",
        },
        "slide_css": """
            .reveal section { text-align: left; }
            .reveal h1, .reveal h2 { color: #FFFFFF; font-weight: 300; letter-spacing: 2px; }
            .reveal h3 { color: #E0E0E0; font-weight: 300; }
            .reveal ul { list-style: none; padding-left: 0; }
            .reveal ul li { padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.1); }
            .reveal blockquote { border-left: 2px solid #E0E0E0; padding-left: 16px; color: #AAAAAA; font-style: italic; }
        """,
    },
    "teal_trust": {
        "id": "teal_trust",
        "name": "青绿信任",
        "description": "白色背景 + 青绿色系，适合医疗、金融、咨询行业",
        "css": {
            "backgroundColor": "#FFFFFF",
            "color": "#1a1a2e",
            "headingColor": "#028090",
            "accentColor": "#00A896",
            "linkColor": "#028090",
            "fontFamily": "'Inter', 'Noto Sans SC', sans-serif",
            "headingFontFamily": "'Inter', 'Noto Sans SC', sans-serif",
            "codeFontFamily": "'Fira Code', monospace",
        },
        "reveal_config": {
            "transition": "slide",
            "backgroundTransition": "slide",
        },
        "slide_css": """
            .reveal section { text-align: left; }
            .reveal h1, .reveal h2 { color: #028090; font-weight: 700; }
            .reveal h3 { color: #00A896; font-weight: 600; }
            .reveal ul li { padding: 6px 0; }
            .reveal code { background: #E0F7FA; padding: 2px 8px; border-radius: 4px; color: #028090; font-size: 0.85em; }
            .reveal blockquote { border-left: 4px solid #00A896; padding-left: 16px; color: #555; background: #F0FFFF; padding: 12px 16px; }
            .reveal table th { background: #028090; color: white; padding: 8px 12px; }
            .reveal table td { border: 1px solid #E0F7FA; padding: 8px 12px; }
        """,
    },
}


def get_theme(theme_id: str) -> dict[str, Any]:
    """
    获取主题配置。

    Args:
        theme_id: 主题标识符

    Returns:
        主题配置字典

    Raises:
        ValueError: 主题不存在
    """
    if theme_id not in THEMES:
        available = list(THEMES.keys())
        raise ValueError(f"未知主题: {theme_id}，可用主题: {available}")
    return THEMES[theme_id]


def get_theme_list() -> list[dict[str, str]]:
    """返回所有可用主题的摘要列表（供前端选择器使用）。"""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "description": t["description"],
        }
        for t in THEMES.values()
    ]


def get_default_theme_id() -> str:
    """返回默认主题 ID。"""
    return "tech_dark"


def build_reveal_html(slides_html: list[str], theme_id: str, title: str = "Presentation") -> str:
    """
    将幻灯片 HTML 列表组装为完整的 reveal.js 页面。

    Args:
        slides_html: 每页幻灯片的 <section> HTML 列表
        theme_id: 主题 ID
        title: 演示文稿标题

    Returns:
        完整的 HTML 字符串
    """
    theme = get_theme(theme_id)
    css_vars = theme["css"]
    slide_css = theme["slide_css"]

    sections = "\n".join(slides_html)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" href="{_REVEAL_JS_BASE}/reveal.min.css">
    <link rel="stylesheet" href="{_REVEAL_JS_BASE}/theme/black.min.css" id="theme">
    <style>
        :root {{
            --r-background-color: {css_vars['backgroundColor']};
            --r-main-color: {css_vars['color']};
            --r-heading-color: {css_vars['headingColor']};
            --r-link-color: {css_vars['linkColor']};
            --r-main-font: {css_vars['fontFamily']};
            --r-heading-font: {css_vars['headingFontFamily']};
            --r-code-font: {css_vars['codeFontFamily']};
        }}
        * {{ box-sizing: border-box; }}
        html, body {{
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            background: {css_vars['backgroundColor']};
        }}
        .reveal {{
            width: 100%;
            height: 100%;
            margin: 0 auto;
            font-size: 26px;
        }}
        .reveal .slides section {{
            padding: 44px 56px;
            overflow: hidden;
            width: 100%;
            height: 100%;
        }}
        .reveal .slides section .slide-content {{
            width: 100%;
            height: 100%;
            transform-origin: top left;
            will-change: transform;
        }}
        .reveal .slides section .slide-content > * {{
            max-width: 100%;
            overflow-wrap: break-word;
            word-break: break-word;
        }}
        .reveal .slides section .slide-content > *:first-child {{ margin-top: 0; }}
        .reveal .slides section .slide-content > *:last-child {{ margin-bottom: 0; }}
        .reveal .slides section h1 {{ font-size: 2.25em; line-height: 1.14; margin: 0 0 0.32em 0; }}
        .reveal .slides section h2 {{ font-size: 1.7em; line-height: 1.2; margin: 0 0 0.3em 0; }}
        .reveal .slides section h3 {{ font-size: 1.26em; line-height: 1.28; margin: 0.38em 0 0.22em; }}
        .reveal .slides section p {{ font-size: 0.96em; line-height: 1.48; margin: 0.24em 0; }}
        .reveal .slides section ul, .reveal .slides section ol {{ font-size: 0.88em; line-height: 1.55; margin: 0.24em 0; padding-left: 1.3em; }}
        .reveal .slides section li {{ margin: 0.18em 0; }}
        .reveal .slides section img, .reveal .slides section video, .reveal .slides section iframe {{ max-width: 100%; max-height: 320px; object-fit: contain; }}
        .reveal .slides section table {{ width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 0.78em; }}
        .reveal .slides section pre {{ max-width: 100%; white-space: pre-wrap; word-break: break-word; font-size: 0.76em; }}
        .reveal .controls {{ display: none !important; }}
        .reveal .progress {{ display: none !important; }}
        .reveal .slide-number {{ display: none !important; }}
        {slide_css}
    </style>
</head>
<body>
    <div class="reveal">
        <div class="slides">
{sections}
        </div>
    </div>
    <script src="{_REVEAL_JS_BASE}/reveal.min.js"></script>
    <script>
        let revealReady = false;

        function ensureSlideContent(section) {{
            const firstElement = section.firstElementChild;
            if (firstElement && firstElement.classList.contains('slide-content')) {{
                return firstElement;
            }}

            const wrapper = document.createElement('div');
            wrapper.className = 'slide-content';
            while (section.firstChild) {{
                wrapper.appendChild(section.firstChild);
            }}
            section.appendChild(wrapper);
            return wrapper;
        }}

        function fitSection(section) {{
            const content = ensureSlideContent(section);
            content.style.transform = 'scale(1)';

            const availableWidth = section.clientWidth;
            const availableHeight = section.clientHeight;
            const requiredWidth = Math.max(content.scrollWidth, availableWidth);
            const requiredHeight = Math.max(content.scrollHeight, availableHeight);
            const scale = Math.min(1, availableWidth / requiredWidth, availableHeight / requiredHeight);

            content.style.transform = `scale(${{scale}})`;
        }}

        function fitAllSlides() {{
            document.querySelectorAll('.reveal .slides > section').forEach((section) => {{
                fitSection(section);
            }});
        }}

        Reveal.initialize({{
            hash: false,
            slideNumber: false,
            transition: 'none',
            backgroundTransition: 'none',
            embedded: true,
            width: 1280,
            height: 720,
            margin: 0,
            center: true,
            keyboard: true,
            autoSlide: 0,
            mouseWheel: false,
            touch: false,
            loop: false,
            rtl: false,
            navigationMode: 'linear',
            shuffle: false,
            fragments: false,
            fragmentInURL: false,
            help: false,
            showNotes: false,
            previewLinks: false,
        }});

        // 监听 postMessage 指令（与父窗口通信）
        window.addEventListener('message', function(event) {{
            const data = event.data;
            if (!data || !data.type) return;

            switch(data.type) {{
                case 'goToSlide':
                    if (!revealReady) return;
                    const index = data.index || 0;
                    Reveal.slide(index, 0, 0);
                    window.parent.postMessage({{
                        type: 'slideChanged',
                        current: index,
                        total: Reveal.getTotalSlides(),
                    }}, '*');
                    break;
                case 'getState':
                    if (!revealReady) return;
                    window.parent.postMessage({{
                        type: 'slideState',
                        current: Reveal.getIndices().h,
                        total: Reveal.getTotalSlides(),
                    }}, '*');
                    break;
                case 'updateSlide':
                    // 动态更新指定幻灯片内容
                    const slides = document.querySelectorAll('.reveal .slides > section');
                    if (data.index < slides.length) {{
                        slides[data.index].innerHTML = data.html;
                        fitSection(slides[data.index]);
                    }}
                    break;
                case 'refitSlides':
                    fitAllSlides();
                    break;
            }}
        }});

        // 翻页时通知父窗口
        Reveal.on('slidechanged', function(event) {{
            fitSection(event.currentSlide);
            window.parent.postMessage({{
                type: 'slideChanged',
                current: event.indexh,
                total: Reveal.getTotalSlides(),
            }}, '*');
        }});

        // 初始化完成后通知
        Reveal.on('ready', function() {{
            fitAllSlides();
            revealReady = true;
            window.parent.postMessage({{
                type: 'revealReady',
                current: Reveal.getIndices().h,
                total: Reveal.getTotalSlides(),
            }}, '*');
        }});

        window.addEventListener('resize', fitAllSlides);
    </script>
</body>
</html>"""
