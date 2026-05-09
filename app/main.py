from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.wecom import router as wecom_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import Encryptor
from app.db.session import init_database
from app.gateways.wecom import WeComGateway
from app.services.scheduler import build_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    encryptor = Encryptor(settings.app_encryption_key.get_secret_value())
    wecom = WeComGateway(settings)

    app.state.settings = settings
    app.state.encryptor = encryptor
    app.state.wecom = wecom

    await init_database()

    scheduler = build_scheduler(settings, encryptor, wecom)
    scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="WeCom DeepSeek Personal Assistant", version="0.1.0", lifespan=lifespan)
app.include_router(wecom_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
