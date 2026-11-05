from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FactView:
    """Факт в виде, удобном для шаблона документа."""

    id: str
    type: str
    title: str
    confidence: float
    status: str
    doc: str | None = None
    frag: int | None = None
    definition: str = ""
    acceptance: str = ""

    @property
    def source(self) -> str:
        """Подпись источника: документ и номер фрагмента."""
        return f"{self.doc}, фрагмент {self.frag}"


@dataclass(frozen=True)
class DocumentContext:
    """Контекст рендера одного документа каркаса."""

    title: str
    facts: tuple[FactView, ...] = field(default_factory=tuple)
    empty_reason: str = ""
    generated: str | None = None
