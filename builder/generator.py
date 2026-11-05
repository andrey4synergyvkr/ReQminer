from __future__ import annotations

import threading

from services.builder.planner import DOCUMENTS_BY_PATH, TEMPLATE_SET
from services.builder.presenter import fact_views
from services.builder.prompts import builder_prompts
from services.common import parallel
from services.common.llm_adapter import get_adapter
from services.common.progress import ProgressTick


def _strip_heading(text: str, title: str) -> str:
    """Убирает заголовок раздела из ответа модели, если он его повторил.

    Шаблон документа сам ставит заголовок; модель должна вернуть тело.
    Если модель прислала раздел целиком, дублирующий заголовок срезается.
    """
    first, _, rest = text.partition("\n")
    if first.strip() != f"# {title}".strip():
        return text.rstrip("\n")
    if rest.startswith("\n"):
        rest = rest[1:]
    return rest.rstrip("\n")


def generate(sections: dict[str, dict],
             *, progress: ProgressTick | None = None) -> dict[str, str]:
    """Генерирует markdown-тексты разделов по плану.

    total включает аналитический отчёт (+1): его пишет service.build
    после разделов, поэтому последний тик прогресса приходит оттуда.
    """
    adapter = get_adapter()
    filled = [rel for rel, section in sections.items() if section["facts"]]
    total = len(filled) + 1
    if progress is not None:
        progress(0, total, "")

    done = 0
    lock = threading.Lock()

    def on_done(rel: str) -> None:
        nonlocal done
        if progress is None:
            return
        with lock:
            done += 1
            current = done
        progress(current, total, sections[rel]["title"])

    generated: dict[str, str] = {}
    if adapter.mode == "cloud":
        prompts_by_rel = {
            rel: builder_prompts.section(
                sections[rel]["title"], sections[rel]["facts"]
            )
            for rel in filled
        }
        texts = parallel.map_calls(
            adapter,
            lambda rel: adapter.complete(
                prompts_by_rel[rel].system, prompts_by_rel[rel].user
            ),
            filled,
            on_done=on_done,
        )
        generated = {
            rel: _strip_heading(text, sections[rel]["title"])
            for rel, text in zip(filled, texts)
            if text
        }
    else:
        # offline: модель не вызывается, но прогресс по разделам идёт
        for rel in filled:
            on_done(rel)

    docs: dict[str, str] = {}
    for rel, section in sections.items():
        spec = DOCUMENTS_BY_PATH[rel]
        docs[rel] = TEMPLATE_SET.render(
            spec.template,
            title=section["title"],
            facts=fact_views(section["facts"]),
            empty_reason=spec.empty_reason or "",
            generated=generated.get(rel),
        )
    return docs
