"""
Конвертация TON-адресов: raw (0:hex) → friendly (UQ…/EQ…).
Локальная реализация без внешних API (CRC16-XMODEM + base64url).
In-memory кэш без TTL (адрес не меняется).
"""
import base64
import logging
import struct
from typing import Dict

logger = logging.getLogger(__name__)

# Кэш: any_address → friendly non-bounceable (UQ…). Адрес неизменен, TTL не нужен.
_cache: Dict[str, str] = {}


def _crc16_xmodem(data: bytes) -> int:
    """CRC16-XMODEM (poly=0x1021) — используется в TON friendly-адресах."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def _raw_to_friendly_local(raw_address: str, bounceable: bool = False) -> str:
    """
    Локальная конвертация raw (0:hex) → friendly base64url (EQ/UQ).
    bounceable=True → tag 0x11 (EQ…), bounceable=False → tag 0x51 (UQ…).
    """
    if ":" not in raw_address:
        return raw_address
    parts = raw_address.split(":", 1)
    try:
        workchain = int(parts[0])
        addr_bytes = bytes.fromhex(parts[1])
    except (ValueError, IndexError):
        return raw_address
    if len(addr_bytes) != 32:
        return raw_address
    tag = 0x11 if bounceable else 0x51
    wc_byte = struct.pack("b", workchain)  # signed byte
    payload = bytes([tag]) + wc_byte + addr_bytes
    crc = _crc16_xmodem(payload)
    full = payload + struct.pack(">H", crc)
    return base64.urlsafe_b64encode(full).decode("ascii").rstrip("=")


def _is_friendly(addr: str) -> bool:
    """Проверяет, является ли адрес уже friendly (UQ/EQ/kQ/0Q)."""
    return bool(addr) and len(addr) >= 48 and addr[:2] in ("EQ", "UQ", "kQ", "0Q")


async def raw_to_friendly(raw_address: str) -> str:
    """
    Конвертирует адрес (raw 0:hex или любой формат) в friendly non-bounceable (UQ…).
    Полностью локальная реализация — без обращений к Ton Center API.
    При ошибке возвращает исходный адрес (fallback).
    """
    if not raw_address or not isinstance(raw_address, str):
        return raw_address or ""
    addr = raw_address.strip()
    if not addr:
        return ""
    # Если уже UQ — вернуть как есть
    if addr.startswith("UQ") and len(addr) >= 48:
        return addr
    # Кэш
    if addr in _cache:
        return _cache[addr]
    # Локальная конвертация
    try:
        friendly = _raw_to_friendly_local(addr, bounceable=False)
        if friendly and friendly != addr:
            _cache[addr] = friendly
            return friendly
    except Exception as e:
        logger.warning("raw_to_friendly error: %s", e)
    # Fallback: вернуть исходный
    return addr
