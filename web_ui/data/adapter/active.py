from __future__ import annotations

from contracts.workflow import PackageStatus
from services.orchestrator.progress import PHASE_DEFS

from .context import UiServices, get_services
from .progress_data import percent, phase_index


def active_run(*, services: UiServices | None = None) -> dict | None:
    """Последний выполняющийся прогон; None, если активных нет."""
    services = services or get_services()
    running = [
        pkg for pkg in services.registry.list_packages()
        if pkg["status"] == PackageStatus.RUN.value
    ]
    if not running:
        return None
    pkg = running[0]
    run = services.registry.get_run(pkg["id"]) or {}
    return {
        "id": pkg["id"],
        "name": pkg["name"],
        "count": len(running),
        "percent": percent(run),
        "phase": PHASE_DEFS[phase_index(run)].short,
    }
