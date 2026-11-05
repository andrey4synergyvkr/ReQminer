from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.web_ui.data import adapter

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=BASE_DIR / "templates")


def render(request: Request, template: str, nav: str, **ctx) -> HTMLResponse:
    """Рендерит экран с общими переменными (nav, пользователь, адаптер)."""
    return TEMPLATES.TemplateResponse(
        request,
        template,
        {"nav": nav, "user": request.state.user, "adapter": adapter, **ctx},
    )
