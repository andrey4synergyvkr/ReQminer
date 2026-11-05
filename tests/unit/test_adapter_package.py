from __future__ import annotations

from pathlib import Path

import services.web_ui.data.adapter as adapter


def test_public_api_resolves():
    assert adapter.__all__
    for name in adapter.__all__:
        assert hasattr(adapter, name), name


def test_adapter_is_package_with_screen_modules():
    assert hasattr(adapter, "__path__")
    modules = {path.stem for path in Path(adapter.__file__).parent.glob("*.py")}
    assert {"core", "packages", "facts", "review", "report", "graph",
            "startup", "markdown"} <= modules


def test_screen_modules_within_size_limit():
    root = Path(adapter.__file__).parent
    for path in root.glob("*.py"):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        assert lines <= 150, f"{path.name}: {lines} строк"
