from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from services.common.logging import configure as configure_logging, get_logger
from services.web_ui.data import adapter
from services.web_ui.routes import facts, graph, packages, report, review

log = get_logger("web_ui")

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Точка сборки приложения: журналирование, каталоги, реестр и сиды."""
    configure_logging()
    log.info("ReQminer UI запущен: журналирование включено (файл logs/reqminer.log)")
    adapter.startup()
    yield


app = FastAPI(title="ReQminer UI", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(packages.router)
app.include_router(facts.router)
app.include_router(review.router)
app.include_router(graph.router)
app.include_router(report.router)


@app.middleware("http")
async def fake_sso(request: Request, call_next):
    """Заглушка входа через корпоративную систему управления доступом."""
    request.state.user = adapter.USER
    return await call_next(request)
