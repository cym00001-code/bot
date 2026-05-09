from __future__ import annotations

import base64
import hashlib
import struct
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class WeComCryptoError(ValueError):
    pass


class WeComCrypto:
    def __init__(self, token: str, encoding_aes_key: str, corp_id: str) -> None:
        if len(encoding_aes_key) != 43:
            raise WeComCryptoError("WE_COM_ENCODING_AES_KEY must be 43 characters")
        self.token = token
        self.corp_id = corp_id
        self.key = base64.b64decode(f"{encoding_aes_key}=")
        if len(self.key) != 32:
            raise WeComCryptoError("decoded EncodingAESKey must be 32 bytes")

    def verify_signature(self, signature: str, timestamp: str, nonce: str, encrypted: str) -> None:
        items = sorted([self.token, timestamp, nonce, encrypted])
        calculated = hashlib.sha1("".join(items).encode("utf-8")).hexdigest()
        if calculated != signature:
            raise WeComCryptoError("invalid WeCom message signature")

    def decrypt(self, encrypted: str) -> str:
        try:
            cipher_bytes = base64.b64decode(encrypted)
        except Exception as exc:
            raise WeComCryptoError("invalid encrypted payload") from exc

        decryptor = Cipher(algorithms.AES(self.key), modes.CBC(self.key[:16])).decryptor()
        padded = decryptor.update(cipher_bytes) + decryptor.finalize()
        plain = self._wechat_pkcs7_unpad(padded)

        if len(plain) < 20:
            raise WeComCryptoError("decrypted payload too short")
        message_length = struct.unpack("!I", plain[16:20])[0]
        message = plain[20 : 20 + message_length].decode("utf-8")
        receive_id = plain[20 + message_length :].decode("utf-8")
        if self.corp_id and receive_id != self.corp_id:
            raise WeComCryptoError("decrypted payload receive id mismatch")
        return message

    def _wechat_pkcs7_unpad(self, padded: bytes) -> bytes:
        if not padded:
            raise WeComCryptoError("empty decrypted payload")
        pad_len = padded[-1]
        if pad_len < 1 or pad_len > 32:
            raise WeComCryptoError("invalid WeCom PKCS7 padding length")
        if padded[-pad_len:] != bytes([pad_len]) * pad_len:
            raise WeComCryptoError("invalid WeCom PKCS7 padding bytes")
        return padded[:-pad_len]

    def verify_url(self, signature: str, timestamp: str, nonce: str, echo_str: str) -> str:
        self.verify_signature(signature, timestamp, nonce, echo_str)
        return self.decrypt(echo_str)


def extract_encrypt_from_xml(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    encrypt_node = root.find("Encrypt")
    if encrypt_node is None or not encrypt_node.text:
        raise WeComCryptoError("missing Encrypt node")
    return encrypt_node.text
