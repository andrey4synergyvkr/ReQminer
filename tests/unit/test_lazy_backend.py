from __future__ import annotations

import threading

from services.common.lazy_backend import LazyBackend


class _Memory:
    pass


def test_factory_called_once():
    calls = {"n": 0}
    fallback = _Memory()

    def factory():
        calls["n"] += 1
        return _Memory()

    lazy = LazyBackend(factory, lambda: fallback)
    first = lazy.backend()
    for _ in range(5):
        assert lazy.backend() is first
    assert calls["n"] == 1


def test_failed_probe_is_sticky_until_reset():
    calls = {"n": 0}
    fallback = _Memory()

    def factory():
        calls["n"] += 1
        return None

    lazy = LazyBackend(factory, lambda: fallback)
    assert lazy.backend() is fallback
    for _ in range(5):
        assert lazy.backend() is fallback
    assert calls["n"] == 1, "отказ не должен проверяться на каждом вызове"

    lazy.reset()
    assert lazy.backend() is fallback
    assert calls["n"] == 2


def test_concurrent_first_call_resolves_once():
    calls = {"n": 0}
    fallback = _Memory()

    def factory():
        calls["n"] += 1
        return _Memory()

    lazy = LazyBackend(factory, lambda: fallback)
    results: list[object] = []
    threads = [
        threading.Thread(target=lambda: results.append(lazy.backend()))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len({id(r) for r in results}) == 1
    assert calls["n"] == 1


def test_use_forces_backend():
    lazy = LazyBackend(lambda: None, _Memory)
    chosen = _Memory()
    lazy.use(chosen)
    assert lazy.backend() is chosen
