from __future__ import annotations

import threading

from contracts.facts import PAIRABLE_TYPES
from contracts.records import Pair
from services.common import parallel
from services.common.llm_adapter import get_adapter
from services.common.progress import ProgressTick
from services.common.text_rules import token_set

# минимум общих значимых токенов, чтобы пара ушла на вердикт.
# 2 - нижняя граница: у пары «экспортировать отчёт/результаты в XLSX»
# значимых общих токенов ровно два (экспо, xlsx); порог 3 её отбросил бы.
_PREFILTER_THRESHOLD = 2


def detect(facts: list[dict], *, adapter=None,
           progress: ProgressTick | None = None) -> list[Pair]:
    """Находит пары-кандидаты; статусы фактов ставит add_pairs репозитория."""
    llm = adapter or get_adapter()
    pairable = [f for f in facts if f.get("type") in PAIRABLE_TYPES]
    # токены считаются один раз на факт: предфильтр не токенизирует пары
    tokens = [token_set(f["title"]) for f in pairable]
    # экономия вызовов: непохожие формулировки не уходят в LlmAdapter
    pairs = [
        (pairable[i], pairable[j])
        for i in range(len(pairable))
        for j in range(i + 1, len(pairable))
        if len(tokens[i] & tokens[j]) >= _PREFILTER_THRESHOLD
    ]
    total = len(pairs)
    if progress is not None:
        progress(0, total, "")

    done = 0
    lock = threading.Lock()

    def on_done(pair) -> None:
        nonlocal done
        if progress is None:
            return
        with lock:
            done += 1
            current = done
        a, b = pair
        progress(current, total, f"{a.get('id', '')} ↔ {b.get('id', '')}")

    verdicts = parallel.map_calls(
        llm, lambda pair: llm.judge_pair(pair[0], pair[1]), pairs,
        on_done=on_done,
    )
    return [
        {"kind": verdict["kind"], "reason": verdict["reason"],
         "a": a["id"], "b": b["id"]}
        for (a, b), verdict in zip(pairs, verdicts)
        if verdict is not None
    ]
