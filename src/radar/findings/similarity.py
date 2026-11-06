"""Что считать одной находкой: нормализация текста и нечёткое сравнение (символьные 5-граммы, Жаккар)."""
import hashlib
import re
import zlib
from array import array

_URL = re.compile(r"(?:https?://|www\.)\S+|\b(?:[\w-]+\.)+[a-z]{2,}/\S*", re.IGNORECASE)
_MENTION = re.compile(r"@\w+")
_HASHTAG = re.compile(r"#\w+")
_NON_WORD = re.compile(r"[^\w\s]|_", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    t = (text or "").lower().replace("ё", "е")
    t = _URL.sub(" ", t)
    t = _MENTION.sub(" ", t)
    t = _HASHTAG.sub(" ", t)
    t = _NON_WORD.sub(" ", t)  # пунктуация и эмодзи
    return _SPACES.sub(" ", t).strip()


def fingerprint(norm: str) -> str:
    return hashlib.sha1(norm.encode()).hexdigest()


def shingles(norm: str, k: int = 5) -> set[int]:
    """Хэши символьных k-грамм. crc32 — стабилен между процессами (значения лежат в БД)."""
    if len(norm) < k:
        return {zlib.crc32(norm.encode())} if norm else set()
    return {zlib.crc32(norm[i:i + k].encode()) for i in range(len(norm) - k + 1)}


def jaccard(a: set[int], b: set[int]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def pack(sh: set[int]) -> bytes:
    return array("I", sorted(sh)).tobytes()


def unpack(blob: bytes) -> set[int]:
    a = array("I")
    a.frombytes(blob)
    return set(a)
