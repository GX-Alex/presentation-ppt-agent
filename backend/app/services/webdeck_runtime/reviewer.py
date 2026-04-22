"""
Deck Reviewer — 审稿器 (对齐 high.md §5.3.6 Deck Reviewer + Page Reviewer)。
负责页级和 deck 级的质量审查：重复检测、风格一致性、目录匹配、结论贯穿。
"""
import json
import logging
import re
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_client import chat as llm_chat
from app.models.tables import DeckPage
from app.services.webdeck_runtime.contracts import ReviewReport
from app.services.webdeck_runtime.state_store import deck_state_store

logger = logging.getLogger(__name__)

RENDER_CHECK_VIEWPORT = {"width": 1280, "height": 720}

PAGE_REVIEW_PROMPT = """你是 Page Reviewer，负责审查单页 Web 演示的质量。

## 审查维度
1. **视觉中心**: 页面是否有明确的视觉焦点
2. **可读性**: 管理层是否能在 15 秒内理解主旨
3. **信息完整**: 是否传递了 PageSpec 中要求的核心信息、最低观点数和必须区块
4. **资产合规**: 图表/架构图是否满足 asset_requirements 中的 purpose、data_dimensions、required_elements、caption
5. **版式约束**: 是否适配 16:9 单页展示，是否出现必须滚动才能理解主体内容的风险
6. **样式一致**: 是否与全局主题一致

## 设计规则逐条检查

当"全局主题要求"中包含 RULE-N 编号的设计规则时，逐条检查以下内容：

| rule_id | 检查项 | 通过条件 | 失败级别 |
|---------|--------|----------|----------|
| RULE-1 | 美学基调 | 整体风格简洁、专业、权威，无花哨装饰/霓虹色/卡通元素 | warning |
| RULE-2 | 排版规则 | 标题使用衬线体(Times New Roman/Garamond)，正文使用无衬线体(Arial/Roboto)，无system-ui/Inter等禁用字体 | error |
| RULE-3 | 配色方案 | 背景白色(#FFFFFF)，文字黑色，主色深宝蓝(#0A2463)，无暗色渐变背景，无#3b82f6等禁用色 | error |
| RULE-4 | 图形规范 | 表格使用≤1px细边框，无box-shadow/text-shadow/perspective/3D效果 | error |
| RULE-5 | 行动标题 | h1/h2是含主语+动词+结论的完整句子(So What)，而非"成本分析""架构概述"类短语 | error |
| RULE-6 | 数据可视化 | 使用了复杂图表/数据表/框架图/矩阵，未用简单列表替代可视化（cover/toc页除外） | warning |
| RULE-7 | 栏式布局 | 使用2-3栏grid/flex布局，信息密度充足，无大面积留白（cover页除外） | warning |
| RULE-8 | 数据完整性 | 未知数字使用[Data: XX%]占位，无明显捏造的数据/来源 | error |
| RULE-9 | HTML结构 | 使用<section class="deck-page">，无<!DOCTYPE>/html/head/body/slide标签 | error |

每条违规必须在 issues 中标注 rule_id，格式: {"level":"error","rule_id":"RULE-5","message":"...","suggestion":"..."}

评分: score = (规则合规度 × 0.5) + (原6维度评分 × 0.5)。任一RULE标记为error级违规 → passed=false

## 审稿原则
- 不要再使用 narrative_contract.max_words 或任何字数上限作为失败条件
- 输入中提供的是用于审稿的清洗摘要，不要因为 style/script 被移除或节选而判定"HTML 内容不完整"
- 只有会直接影响页面目标达成或展示完整性的缺陷才标记为 error，其余问题给 warning

## 输出要求
输出 JSON:
```json
{
  "passed": true/false,
  "score": 0.0-1.0,
  "issues": [
    {"level": "warning|error", "rule_id": "RULE-N（如适用）", "message": "问题描述", "suggestion": "改进建议"}
  ],
  "suggestions": ["总体改进建议"]
}
```

只输出 JSON。"""

DECK_REVIEW_PROMPT = """你是 Deck Reviewer，负责整份 Web 演示的跨页审查。

## 审查维度 (对齐 high.md §5.3.6)
1. **重复检测**: 页面间是否有内容重复
2. **节奏合理**: 信息密度是否合理递进
3. **风格一致**: 全部页面是否统一遵循设计规则——特别关注：
   - 是否所有页面都使用白色背景+深宝蓝主色（无页面用暗色主题）
   - 是否所有页面标题都是 So What 结论句（无短语标题混入）
   - 是否字体统一（无页面使用 system-ui/Inter 等非规定字体）
4. **目录匹配**: 目录与实际页面是否一致
5. **结论贯穿**: 核心结论是否贯穿全篇
6. **覆盖完整**: 关键页面是否真的承担了各自的角色，没有出现关键论证缺口
7. **单页约束一致**: 是否普遍满足 16:9 单页展示和信息块分配要求

## 输出要求
输出 JSON:
```json
{
  "passed": true/false,
  "score": 0.0-1.0,
  "issues": [
    {"level": "warning|error", "rule_id": "RULE-N（如适用）", "message": "问题描述", "suggestion": "改进建议"}
  ],
  "suggestions": ["总体改进建议"]
}
```

只输出 JSON。"""


class DeckReviewer:
    """审稿器 — 页级和 deck 级质量审查"""

    @staticmethod
    def _programmatic_style_checks(html: str, design_rules: str) -> list[dict[str, Any]]:
        """对可用正则判定的规则做程序化预检，补充 LLM 审稿的盲点"""
        if "RULE-" not in design_rules:
            return []
        issues: list[dict[str, Any]] = []
        html_lower = html.lower()
        # RULE-4: box-shadow / text-shadow / perspective
        for prop in ["box-shadow", "text-shadow"]:
            if re.search(rf'{prop}\s*:', html, re.I):
                issues.append({"level": "error", "rule_id": "RULE-4",
                               "message": f"检测到 {prop} 声明", "suggestion": f"移除所有 {prop}"})
        if re.search(r'transform\s*:[^;]*perspective', html, re.I):
            issues.append({"level": "error", "rule_id": "RULE-4",
                           "message": "检测到 perspective 3D 变换", "suggestion": "移除 perspective"})
        # RULE-7: 多栏布局（cover/toc 页由调用方控制是否跳过）
        if not re.search(r'grid-template-columns|display\s*:\s*flex', html):
            issues.append({"level": "warning", "rule_id": "RULE-7",
                           "message": "未检测到多栏布局结构", "suggestion": "使用 grid-template-columns 实现 2-3 栏布局"})
        # RULE-3: 暗色背景
        dark_bg = re.findall(r'background[^:]*:\s*[^;]*(#0[0-3f][0-9a-f]{4}|#1[0-9a-e][0-9a-f]{4})', html, re.I)
        for match in dark_bg:
            if match.lower() not in ("#0a2463",):
                issues.append({"level": "error", "rule_id": "RULE-3",
                               "message": f"检测到暗色背景值 {match}", "suggestion": "改为 #FFFFFF"})
        # RULE-3: 禁用色
        for banned in ["#3b82f6", "#8b5cf6", "#ec4899", "#93c5fd"]:
            if banned in html_lower:
                issues.append({"level": "warning", "rule_id": "RULE-3",
                               "message": f"检测到非规定色 {banned}", "suggestion": "替换为 #0A2463 或灰阶辅助色"})
        # RULE-9: HTML 结构
        if '<!doctype' in html_lower or '<html' in html_lower:
            issues.append({"level": "error", "rule_id": "RULE-9",
                           "message": "输出了完整 HTML 文档而非 section 片段", "suggestion": "只输出 <section> 片段"})
        # RULE-2: 禁用字体
        for banned_font in ["system-ui", "Inter,", "Montserrat"]:
            if banned_font.lower() in html_lower:
                issues.append({"level": "warning", "rule_id": "RULE-2",
                               "message": f"检测到非规定字体 {banned_font}", "suggestion": "标题用 Times New Roman，正文用 Arial"})
        return issues

    @staticmethod
    def _sanitize_html_for_review(html: str) -> tuple[str, str]:
        cleaned = re.sub(r"<style\b[^>]*>[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
        cleaned = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        visible_text = re.sub(r"<[^>]+>", " ", cleaned)
        visible_text = re.sub(r"\s+", " ", visible_text).strip()
        return cleaned[:12000], visible_text[:8000]

    @staticmethod
    def _summarize_bundle(page: DeckPage) -> str:
        bundle = page.page_bundle or {}
        artifacts = bundle.get("artifacts") or []
        if not artifacts:
            return "无"

        lines: list[str] = []
        for artifact in artifacts[:6]:
            kind = str(artifact.get("kind") or "asset")
            metadata = artifact.get("metadata") or {}
            lines.append(f"- {kind}: {json.dumps(metadata, ensure_ascii=False)}")
            content_preview = str(metadata.get("content_preview") or "").strip()
            if not content_preview:
                content_preview = re.sub(r"\s+", " ", str(artifact.get("content") or "")).strip()[:280]
            if content_preview:
                lines.append(f"  preview: {content_preview[:280]}")
        return "\n".join(lines)

    @staticmethod
    def _normalize_report(report: ReviewReport, review_level: str = "page") -> ReviewReport:
        normalized_issues = []
        has_error = False
        for issue in report.issues:
            level = str(issue.get("level") or "warning").lower()
            message = str(issue.get("message") or "").strip()
            suggestion = str(issue.get("suggestion") or "").strip()
            if not message:
                continue
            if review_level == "deck" and level == "error":
                if "风格" in message or "背景" in message or "封面" in message:
                    level = "warning"
            if level == "error":
                has_error = True
            normalized_issues.append({
                "level": level,
                "rule_id": issue.get("rule_id") or None,
                "message": message,
                "suggestion": suggestion or None,
            })

        report.issues = normalized_issues
        report.passed = False if has_error else True
        return report

    @staticmethod
    def _merge_runtime_issues(report: ReviewReport, runtime_issues: list[dict[str, Any]]) -> ReviewReport:
        if not runtime_issues:
            return report

        report.issues = [*report.issues, *runtime_issues]
        if any(str(issue.get("level") or "warning").lower() == "error" for issue in runtime_issues):
            report.passed = False
            report.score = min(report.score or 0.45, 0.45)

        if not any("16:9" in str(item) or "单页" in str(item) for item in report.suggestions):
            report.suggestions.append("缩小字号或调整布局间距，确保所有关键内容在 16:9 单页画布内完整闭合，而非删减文字内容。")

        return report

    @staticmethod
    def _build_render_check_document(html: str) -> str:
        return f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <style>
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #FFFFFF;
    }}

    body {{
      display: flex;
      align-items: stretch;
      justify-content: stretch;
    }}

    body > * {{
      flex: 1 1 auto;
    }}
  </style>
</head>
<body>
{html}
</body>
</html>"""

    async def _check_render_overflow(self, html: str) -> list[dict[str, Any]]:
        try:
            from app.services.browser_pool import is_pool_ready, managed_page
        except Exception as exc:  # pragma: no cover - import/runtime guard
            logger.warning("[DeckReviewer] 浏览器池不可用，跳过渲染越界检查: %s", exc)
            return []

        if not is_pool_ready():
            return []

        document = self._build_render_check_document(html)

        try:
            async with managed_page() as page:
                await page.set_viewport_size(RENDER_CHECK_VIEWPORT)
                await page.set_content(document, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=1200)
                except Exception:
                    pass
                await page.wait_for_timeout(600)
                metrics = await page.evaluate(
                    r"""
                    () => {
                      const root = document.querySelector('[data-page-id]') || document.querySelector('section') || document.body.firstElementChild || document.body;
                      const viewportWidth = window.innerWidth;
                      const viewportHeight = window.innerHeight;
                      const rootOverflowY = root.scrollHeight - root.clientHeight > 4;
                      const rootOverflowX = root.scrollWidth - root.clientWidth > 4;

                      const offscreenNodes = Array.from(root.querySelectorAll('*')).filter((node) => {
                        const style = window.getComputedStyle(node);
                        if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || '1') === 0) {
                          return false;
                        }
                        const rect = node.getBoundingClientRect();
                        if (rect.width < 8 || rect.height < 8) {
                          return false;
                        }
                        return rect.bottom > viewportHeight + 4 || rect.right > viewportWidth + 4 || rect.top < -4 || rect.left < -4;
                      });

                      const scrollContainers = Array.from(root.querySelectorAll('*')).filter((node) => {
                        const style = window.getComputedStyle(node);
                        const overflowY = style.overflowY;
                        const overflowX = style.overflowX;
                        const scrollableY = (overflowY === 'auto' || overflowY === 'scroll') && node.scrollHeight - node.clientHeight > 4;
                        const scrollableX = (overflowX === 'auto' || overflowX === 'scroll') && node.scrollWidth - node.clientWidth > 4;
                        return scrollableY || scrollableX;
                      });

                      return {
                        rootOverflowY,
                        rootOverflowX,
                        offscreenCount: offscreenNodes.length,
                        offscreenNames: offscreenNodes.slice(0, 4).map((node) => {
                          const className = typeof node.className === 'string' ? node.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
                          return node.tagName.toLowerCase() + (className ? '.' + className : '');
                        }),
                        scrollContainersCount: scrollContainers.length,
                      };
                    }
                    """
                )
        except Exception as exc:  # pragma: no cover - browser runtime dependent
            logger.warning("[DeckReviewer] 渲染越界检查失败，回退到 LLM 审稿: %s", exc)
            return []

        issues: list[dict[str, Any]] = []
        if metrics.get("rootOverflowY") or metrics.get("rootOverflowX") or metrics.get("offscreenCount") or metrics.get("scrollContainersCount"):
            problem_parts: list[str] = []
            if metrics.get("rootOverflowY"):
                problem_parts.append("主体内容高度超出单页画布")
            if metrics.get("rootOverflowX"):
                problem_parts.append("主体内容宽度超出单页画布")
            if metrics.get("offscreenCount"):
                problem_parts.append(f"有 {metrics.get('offscreenCount')} 个元素落在可视区域之外")
            if metrics.get("scrollContainersCount"):
                problem_parts.append(f"检测到 {metrics.get('scrollContainersCount')} 个内部滚动容器")

            detail = "；".join(problem_parts) or "页面存在 16:9 单页越界风险"
            names = metrics.get("offscreenNames") or []
            if names:
                detail = f"{detail}。疑似越界元素: {', '.join(names)}"

            issues.append({
                "level": "error",
                "message": f"页面未通过 16:9 单页边界检查：{detail}",
                "suggestion": "缩小字号或调整布局间距，确保所有关键内容在首屏闭合，而非删减文字内容。",
            })

        return issues

    async def check_page_overflow(self, html: str) -> list[dict[str, Any]]:
        """公开接口: 仅执行浏览器渲染溢出检查，不调用 LLM。"""
        return await self._check_render_overflow(html)

    async def review_page(
        self,
        session: AsyncSession,
        page: DeckPage,
        project_id: str,
        global_theme: dict,
        model: str | None = None,
    ) -> ReviewReport:
        """页级审稿"""
        page_spec = page.page_spec or {}
        html = page.html or ""

        if not html:
            return ReviewReport(passed=False, score=0.0, issues=[{
                "level": "error",
                "message": "页面没有 HTML 内容",
                "suggestion": "需要重新生成该页面",
            }])

        cleaned_html, visible_text = self._sanitize_html_for_review(html)
        bundle_summary = self._summarize_bundle(page)

        # 提取主题信息供审稿 LLM 校验风格一致性
        _bg = global_theme.get("bg_color", "#FFFFFF")
        _text = global_theme.get("text_color", "#000000")
        _accent = global_theme.get("accent_color", "#0A2463")
        _fh = global_theme.get("font_heading", "serif")
        _fb = global_theme.get("font_body", "sans-serif")
        _dr = global_theme.get("design_rules", "")

        user_content = (
            f"## 全局主题要求\n"
            f"背景色: {_bg}，文字色: {_text}，强调色: {_accent}\n"
            f"标题字体: {_fh}；正文字体: {_fb}\n"
            f"设计规则: {_dr or '无'}\n\n"
            f"## 页面规格\n{json.dumps(page_spec, ensure_ascii=False, indent=2)}\n\n"
            f"## 页面 HTML 结构摘要\n{cleaned_html}\n\n"
            f"## 页面可见文本摘要\n{visible_text or '无'}\n\n"
            f"## 页面资产摘要\n{bundle_summary}\n\n"
            f"请审查此页面质量，特别注意是否符合上述全局主题要求。"
        )

        response = await llm_chat(
            system=PAGE_REVIEW_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            model=model,
        )

        report = self._normalize_report(self._parse_review(response.content), review_level="page")

        # 程序化风格预检，合并到 LLM 审稿结果
        programmatic_issues = self._programmatic_style_checks(html, _dr)
        if programmatic_issues:
            report.issues = programmatic_issues + report.issues
            if any(i["level"] == "error" for i in programmatic_issues):
                report.passed = False
                report.score = min(report.score or 0.45, 0.5)

        report = self._merge_runtime_issues(report, await self._check_render_overflow(html))

        # 持久化页级审稿报告
        await deck_state_store.save_review(
            session=session,
            project_id=project_id,
            page_db_id=page.id,
            level="page",
            passed=report.passed,
            score=report.score,
            issues=report.issues,
            suggestions=report.suggestions,
        )

        return report

    async def review_deck(
        self,
        session: AsyncSession,
        project_id: str,
        model: str | None = None,
    ) -> ReviewReport:
        """Deck 级跨页审稿"""
        from app.services.webdeck_runtime.contracts import DeckManifest

        project = await deck_state_store.get_project(session, project_id)
        if not project:
            return ReviewReport(passed=False, score=0.0, issues=[{
                "level": "error",
                "message": "项目不存在",
                "suggestion": "检查项目 ID",
            }])

        manifest = DeckManifest.from_dict(project.manifest or {})
        pages = await deck_state_store.get_pages(session, project_id)

        # 构建审查上下文（只取每页前 500 字符，避免 token 爆炸）
        page_summaries = []
        for p in pages:
            cleaned_html, visible_text = self._sanitize_html_for_review(p.html or "")
            page_summaries.append(
                f"### {p.page_id}: {p.title} ({p.page_kind})\n"
                f"状态: {p.status}\n"
                f"页面结构摘要: {cleaned_html[:500]}\n"
                f"可见文本摘要: {visible_text[:220]}\n"
            )

        # 提取主题信息
        _gt = manifest.global_theme
        _theme_desc = (
            f"背景色: {_gt.bg_color}，文字色: {_gt.text_color}，强调色: {_gt.accent_color}\n"
            f"标题字体: {_gt.font_heading}；正文字体: {_gt.font_body}\n"
            f"设计规则: {_gt.design_rules or '无'}"
        )

        user_content = (
            f"## Deck 信息\n"
            f"标题: {manifest.title}\n"
            f"目录: {', '.join(manifest.toc)}\n"
            f"总页数: {len(pages)}\n\n"
            f"## 全局主题要求\n{_theme_desc}\n\n"
            f"## 各页面摘要\n{''.join(page_summaries)}\n\n"
            f"请审查整份 Deck 的跨页质量，特别注意风格是否符合上述全局主题要求。"
        )

        response = await llm_chat(
            system=DECK_REVIEW_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            model=model,
        )

        report = self._normalize_report(self._parse_review(response.content), review_level="deck")

        # 保存审稿报告
        await deck_state_store.save_review(
            session=session,
            project_id=project_id,
            page_db_id=None,  # deck 级审稿
            level="deck",
            passed=report.passed,
            score=report.score,
            issues=report.issues,
            suggestions=report.suggestions,
        )

        return report

    def _parse_review(self, content: str) -> ReviewReport:
        """解析 LLM 审稿输出"""
        # 提取 JSON
        json_str = content.strip()
        match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', json_str)
        if match:
            json_str = match.group(1).strip()
        else:
            match = re.search(r'\{[\s\S]*\}', json_str)
            if match:
                json_str = match.group(0).strip()

        try:
            data = json.loads(json_str)
            return ReviewReport(
                passed=data.get("passed", False),
                score=float(data.get("score", 0.0)),
                issues=data.get("issues", []),
                suggestions=data.get("suggestions", []),
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[Reviewer] 审稿输出解析失败: {e}")
            return ReviewReport(
                passed=True,
                score=0.7,
                issues=[],
                suggestions=["审稿结果解析失败，建议人工复查"],
            )
