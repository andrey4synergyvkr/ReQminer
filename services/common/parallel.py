from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from services.common import settings


def worker_count(adapter) -> int:
    """Число потоков для вызовов модели; 0 - последовательный режим.

    Задаётся переменной LLM_CONCURRENCY (0 отключает конкурентность).
    """
    if adapter.mode != "cloud":
        return 0
    return settings.llm_concurrency()


def map_calls(
    adapter,
    call: Callable[[Any], Any],
    items: list,
    *,
    on_done: Callable[[Any], None] | None = None,
) -> list:
    """Вызывает call(item) для всех items: в облаке конкурентно, иначе подряд.

    on_done вызывается после каждого вызова, в том числе при исключении:
    так сервисы сообщают прогресс, не зная, в каком потоке шёл вызов.
    """
    def wrapped(item):
        try:
            return call(item)
        finally:
            if on_done is not None:
                on_done(item)

    count = worker_count(adapter)
    if count < 2 or len(items) < 2:
        return [wrapped(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(count, len(items))) as pool:
        return list(pool.map(wrapped, items))
