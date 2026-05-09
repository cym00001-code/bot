from __future__ import annotations

import base64
import hashlib
import os
import struct
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.gateways.wecom_crypto import WeComCrypto, extract_encrypt_from_xml


def _encrypt_message(plain_xml: str, corp_id: str, encoding_aes_key: str) -> str:
    key = base64.b64decode(f"{encoding_aes_key}=")
    payload = (
        os.urandom(16)
        + struct.pack("!I", len(plain_xml.encode("utf-8")))
        + plain_xml.encode("utf-8")
        + corp_id.encode("utf-8")
    )
    pad_len = 32 - (len(payload) % 32)
    padded = payload + bytes([pad_len]) * pad_len
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode("utf-8")


def test_wecom_crypto_decrypts_signed_message() -> None:
    token = "token123"
    corp_id = "ww123456"
    encoding_aes_key = base64.b64encode(os.urandom(32)).decode("utf-8")[:43]
    plain_xml = "<xml><FromUserName><![CDATA[user1]]></FromUserName><Content><![CDATA[hi]]></Content></xml>"
    encrypted = _encrypt_message(plain_xml, corp_id, encoding_aes_key)
    timestamp = "1777777777"
    nonce = "abc"
    signature = hashlib.sha1("".join(sorted([token, timestamp, nonce, encrypted])).encode()).hexdigest()
    wrapped = f"<xml><Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>"

    extracted = extract_encrypt_from_xml(wrapped)
    decrypted = WeComCrypto(token, encoding_aes_key, corp_id).verify_url(
        signature, timestamp, nonce, extracted
    )

    root = ET.fromstring(decrypted)
    assert root.find("FromUserName").text == "user1"
    assert root.find("Content").text == "hi"
