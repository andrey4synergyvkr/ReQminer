from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class LazyBackend(Generic[T]):
    """Ленивый синглтон бэкенда с липким решением и сбросом для тестов."""

    def __init__(
        self,
        factory: Callable[[], T | None],
        fallback: Callable[[], T],
    ) -> None:
        self._factory = factory
        self._fallback = fallback
        self._backend: T | None = None
        self._resolved = False
        self._lock = threading.RLock()

    @property
    def resolved(self) -> bool:
        """Принято ли уже решение о бэкенде."""
        with self._lock:
            return self._resolved

    def backend(self) -> T:
        """Выбранный бэкенд; при первом обращении решает и запоминает."""
        with self._lock:
            if not self._resolved:
                selected = self._factory()
                self._backend = selected if selected is not None else self._fallback()
                self._resolved = True
            return self._backend  # type: ignore[return-value]

    def use(self, backend: T) -> None:
        """Принудительно выбрать бэкенд (configure, тесты)."""
        with self._lock:
            self._backend = backend
            self._resolved = True

    def reset(self) -> None:
        """Сбросить решение (тесты: смена настроек без перезапуска)."""
        with self._lock:
            self._backend = None
            self._resolved = False

    def backend_name(self) -> str:
        """Имя выбранного бэкенда для логов и диагностики."""
        return type(self.backend()).__name__
