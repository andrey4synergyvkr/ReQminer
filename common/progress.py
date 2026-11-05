from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ProgressTick(Protocol):
    """Сообщение о завершённой единице работы внутри фазы."""

    def __call__(self, done: int, total: int, detail: str = "") -> None: ...
