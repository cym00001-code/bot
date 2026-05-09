from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.gateways.wecom_crypto import WeComCrypto, extract_encrypt_from_xml
from app.schemas import IncomingMessage

logger = logging.getLogger(__name__)


@dataclass
class WeComAccessToken:
    value: str
    expires_at: float


class WeComGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._token: WeComAccessToken | None = None

    def verify_url(self, signature: str, timestamp: str, nonce: str, echo_str: str) -> str:
        crypto = self._crypto()
        if crypto is None:
            return echo_str
        return crypto.verify_url(signature, timestamp, nonce, echo_str)

    def parse_callback(
        self,
        body: bytes,
        signature: str | None,
        timestamp: str | None,
        nonce: str | None,
    ) -> IncomingMessage:
        xml_text = body.decode("utf-8")
        crypto = self._crypto()
        if crypto is not None:
            encrypted = extract_encrypt_from_xml(xml_text)
            if not signature or not timestamp or not nonce:
                raise ValueError("missing WeCom signature parameters")
            crypto.verify_signature(signature, timestamp, nonce, encrypted)
            xml_text = crypto.decrypt(encrypted)
        return self._parse_plain_xml(xml_text)

    async def send_text(self, user_id: str, content: str) -> bool:
        if not self.settings.has_wecom_send_credentials:
            logger.info("WeCom send skipped because credentials are incomplete")
            return False

        token = await self._access_token()
        payload: dict[str, Any] = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": int(self.settings.we_com_agent_id),
            "text": {"content": content[:1900]},
            "safe": 0,
            "enable_duplicate_check": 0,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://qyapi.weixin.qq.com/cgi-bin/message/send",
                params={"access_token": token},
                json=payload,
            )
            data = response.json()
        if data.get("errcode") != 0:
            logger.warning("WeCom send failed: %s", data)
            return False
        return True

    async def _access_token(self) -> str:
        now = time.time()
        if self._token and self._token.expires_at - 60 > now:
            return self._token.value

        secret = self.settings.we_com_secret.get_secret_value()  # type: ignore[union-attr]
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                params={"corpid": self.settings.we_com_corp_id, "corpsecret": secret},
            )
            data = response.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"failed to get WeCom access token: {data}")
        self._token = WeComAccessToken(
            value=data["access_token"],
            expires_at=now + int(data.get("expires_in", 7200)),
        )
        return self._token.value

    def _crypto(self) -> WeComCrypto | None:
        if not self.settings.has_wecom_crypto:
            return None
        aes_key = self.settings.we_com_encoding_aes_key.get_secret_value()  # type: ignore[union-attr]
        return WeComCrypto(self.settings.we_com_token, aes_key, self.settings.we_com_corp_id)

    def _parse_plain_xml(self, xml_text: str) -> IncomingMessage:
        root = ET.fromstring(xml_text)

        def text(name: str) -> str:
            node = root.find(name)
            return node.text if node is not None and node.text else ""

        return IncomingMessage(
            sender_id=text("FromUserName"),
            receiver_id=text("ToUserName"),
            content=text("Content"),
            message_type=text("MsgType") or "text",
            message_id=text("MsgId") or None,
            raw_payload={child.tag: child.text for child in root},
        )
