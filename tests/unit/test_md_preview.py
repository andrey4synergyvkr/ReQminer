from __future__ import annotations

from services.web_ui.data.adapter import md_to_html


def test_headings_lists_and_tables():
    html = md_to_html(
        "# Заголовок\n\n"
        "- **F-001: X** — факт\n\n"
        "| Метрика | Значение |\n|---|---|\n| фактов | 9 |\n"
    )
    assert "<h1>Заголовок</h1>" in html
    assert "<li><strong>F-001: X</strong> — факт</li>" in html
    assert "<table>" in html
    assert "<td>фактов</td>" in html


def test_html_is_escaped():
    html = md_to_html("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_javascript_link_is_blocked():
    html = md_to_html("[клик](javascript:alert)")
    assert "<a " not in html, "ссылка javascript: не должна стать href"
    assert "клик" in html


def test_regular_link_is_rendered():
    html = md_to_html("[клик](https://example.com)")
    assert 'href="https://example.com"' in html
