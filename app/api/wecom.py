from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from app.core.config import Settings
from app.core.security import Encryptor
from app.db.session import AsyncSessionLocal
from app.gateways.wecom import WeComGateway
from app.schemas import IncomingMessage
from app.services.message_processor import MessageProcessor, UnauthorizedUserError

logger = logging.getLogger(__name__)

router = APIRouter()


class DebugChatRequest(BaseModel):
    text: str


async def process_and_send(
    incoming: IncomingMessage,
    settings: Settings,
    encryptor: Encryptor,
    wecom: WeComGateway,
) -> None:
    async with AsyncSessionLocal() as session:
        try:
            reply = await MessageProcessor(session, settings, encryptor).process(incoming)
            await session.commit()
        except UnauthorizedUserError:
            await session.rollback()
            logger.warning("ignored unauthorized WeCom user: %s", incoming.sender_id)
            return
        except Exception:
            await session.rollback()
            logger.exception("failed to process incoming message")
            reply = "我处理这条消息时出错了，稍后你可以再发一次。"

    await wecom.send_text(incoming.sender_id, reply)


@router.get("/wecom/callback")
async def verify_callback(
    request: Request,
    msg_signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    echostr: str = "",
) -> PlainTextResponse:
    wecom: WeComGateway = request.app.state.wecom
    try:
        plain = wecom.verify_url(msg_signature, timestamp, nonce, echostr)
    except Exception as exc:
        logger.warning("WeCom URL verification failed: %s", exc)
        raise HTTPException(status_code=403, detail="invalid signature") from exc
    return PlainTextResponse(plain)


@router.post("/wecom/callback")
async def receive_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    msg_signature: str | None = None,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> PlainTextResponse:
    settings: Settings = request.app.state.settings
    encryptor: Encryptor = request.app.state.encryptor
    wecom: WeComGateway = request.app.state.wecom
    body = await request.body()
    try:
        incoming = wecom.parse_callback(body, msg_signature, timestamp, nonce)
    except Exception as exc:
        logger.warning("invalid WeCom callback: %s", exc)
        raise HTTPException(status_code=400, detail="invalid callback") from exc

    background_tasks.add_task(process_and_send, incoming, settings, encryptor, wecom)
    return PlainTextResponse("success")


@router.post("/debug/chat")
async def debug_chat(request: Request, payload: DebugChatRequest) -> JSONResponse:
    settings: Settings = request.app.state.settings
    if not settings.debug_routes_enabled:
        raise HTTPException(status_code=404, detail="debug routes disabled")

    encryptor: Encryptor = request.app.state.encryptor
    sender = settings.owner_we_com_user_id or "debug-owner"
    incoming = IncomingMessage(
        sender_id=sender,
        receiver_id=settings.we_com_corp_id or "debug-app",
        content=payload.text,
        raw_payload={"debug": True},
    )
    async with AsyncSessionLocal() as session:
        reply = await MessageProcessor(session, settings, encryptor).process(incoming)
        await session.commit()
    return JSONResponse({"reply": reply})
