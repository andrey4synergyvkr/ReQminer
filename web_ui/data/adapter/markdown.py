from __future__ import annotations

from markdown_it import MarkdownIt

# commonmark + таблицы GFM: каркас содержит таблицы метрик, списки фактов
# и ссылки. html=False - HTML из текста экранируется (предпросмотр строится
# как innerHTML диалога, вставлять разметку модели в него нельзя).
_markdown = MarkdownIt("commonmark", {"html": False}).enable("table")


def md_to_html(md_text: str) -> str:
    """Markdown каркаса в HTML для диалога предпросмотра."""
    return _markdown.render(md_text)
