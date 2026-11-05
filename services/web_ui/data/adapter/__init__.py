from __future__ import annotations

import sys
from pathlib import Path

# Доступ к contracts/ и сервисам независимо от рабочего каталога запуска.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from .core import (  # noqa: E402
    ALLOWED_FORMATS,
    DATA_DIR,
    DEFAULT_PACKAGE,
    DIRECTIONS,
    DOC_TYPES,
    FACT_STATUS_CSS,
    FACT_STATUS_LABELS,
    FACT_TYPE_LABELS,
    FACT_TYPE_ORDER,
    FACT_TYPES,
    PACKAGE_STATUS_LABELS,
    POLL_SECONDS,
    UPLOADS_DIR,
    USER,
    fact_type_label,
    get_package,
    list_packages,
    package_status_css,
    package_status_label,
    resolve_package,
)
from .context import (  # noqa: E402
    UiServices,
    configure_services,
    get_services,
    reset_services,
)
from .startup import startup  # noqa: E402
from .packages import create_package, start_analysis  # noqa: E402
from .facts import (  # noqa: E402
    fact_source_label,
    facts_total,
    get_fact,
    get_fragment,
    list_facts,
    pending_count,
)
from .review import (  # noqa: E402
    REVIEW_ACTIONS,
    review_data,
    review_facts,
    review_pair,
)
from .run import get_run, get_run_view, run_state_line  # noqa: E402
from .progress import progress_view  # noqa: E402
from .progress_data import progress_percent  # noqa: E402
from .active import active_run  # noqa: E402
from .graph import (  # noqa: E402
    NodeKind,
    get_graph,
    graph_stats,
    project_graph,
)
from .report import (  # noqa: E402
    OUTBOX_SECTIONS,
    export_outbox_zip,
    get_outbox_doc,
    get_report,
)
from .markdown import md_to_html  # noqa: E402

__all__ = [
    "ALLOWED_FORMATS", "DATA_DIR", "DEFAULT_PACKAGE", "DIRECTIONS", "DOC_TYPES",
    "FACT_STATUS_CSS", "FACT_STATUS_LABELS", "FACT_TYPE_LABELS",
    "FACT_TYPE_ORDER", "FACT_TYPES", "PACKAGE_STATUS_LABELS", "POLL_SECONDS",
    "UPLOADS_DIR", "USER", "NodeKind", "OUTBOX_SECTIONS", "REVIEW_ACTIONS",
    "UiServices", "active_run", "configure_services", "get_services",
    "reset_services",
    "create_package", "export_outbox_zip", "fact_source_label",
    "fact_type_label", "facts_total", "get_fact", "get_fragment", "get_graph",
    "get_outbox_doc", "get_package", "get_report", "get_run", "get_run_view",
    "graph_stats", "list_facts", "list_packages", "md_to_html",
    "package_status_css", "package_status_label", "pending_count",
    "progress_percent", "progress_view",
    "project_graph", "resolve_package", "review_data", "review_facts",
    "review_pair", "run_state_line", "start_analysis", "startup",
]
