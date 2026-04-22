from app.services.webdeck_runtime.contracts import ReviewReport
from app.services.webdeck_runtime.reviewer import DeckReviewer


def test_deck_reviewer_downgrades_style_only_issue_to_warning() -> None:
    report = ReviewReport(
        passed=False,
        score=0.62,
        issues=[
            {
                "level": "error",
                "message": "视觉风格严重不一致：封面与内容页背景深浅不统一。",
                "suggestion": "统一背景色。",
            }
        ],
    )

    normalized = DeckReviewer._normalize_report(report, review_level="deck")

    assert normalized.passed is True
    assert normalized.issues[0]["level"] == "warning"


def test_deck_reviewer_keeps_structural_issue_blocking() -> None:
    report = ReviewReport(
        passed=False,
        score=0.4,
        issues=[
            {
                "level": "error",
                "message": "目录与实际页面严重不匹配。",
                "suggestion": "重建目录。",
            }
        ],
    )

    normalized = DeckReviewer._normalize_report(report, review_level="deck")

    assert normalized.passed is False
    assert normalized.issues[0]["level"] == "error"


def test_merge_runtime_issues_marks_page_blocking() -> None:
    report = ReviewReport(
        passed=True,
        score=0.92,
        issues=[],
        suggestions=[],
    )

    merged = DeckReviewer._merge_runtime_issues(
        report,
        [
            {
                "level": "error",
                "message": "页面未通过 16:9 单页边界检查：主体内容高度超出单页画布。",
                "suggestion": "压缩页面内容。",
            }
        ],
    )

    assert merged.passed is False
    assert merged.score == 0.45
    assert any(issue["level"] == "error" for issue in merged.issues)
    assert any("16:9" in suggestion for suggestion in merged.suggestions)