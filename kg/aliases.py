from __future__ import annotations

import re
import unicodedata


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"[\s\-—_，。！？、；：,.!?;:()（）\[\]{}<>《》/]+", "", text)


# v0.x deterministic aliases used only for entity linking / direct-mention
# detection. Once the KG gains a first-class `aliases` property, these entries
# should move into KG data instead of continuing to grow in code.
_COMMON_ALIASES: dict[str, tuple[str, ...]] = {
    _norm("辅助存储"): ("辅存", "辅助存储器"),
    _norm("Secondary Storage"): ("辅存", "辅助存储", "辅助存储器"),
    _norm("主存"): ("主存储器", "主内存"),
    _norm("Main Memory"): ("主存", "主存储器", "主内存"),
    _norm("高速缓存"): ("缓存", "Cache"),
    _norm("Cache"): ("高速缓存", "缓存"),
    _norm("动态随机存取存储器"): ("DRAM",),
    _norm("Dynamic Random Access Memory"): ("DRAM",),
    _norm("静态随机存取存储器"): ("SRAM",),
    _norm("Static Random Access Memory"): ("SRAM",),
}


def aliases_for(name: str, name_en: str) -> list[str]:
    """Return deterministic name/alias variants for v0.x entity linking."""
    raw = f"{name};{name_en}"
    variants: list[str] = []

    # Preserve common slash acronyms such as I/O before splitting.
    variants.extend(re.findall(r"[A-Za-z](?:/[A-Za-z])+", raw))
    for whole in (name, name_en):
        whole = str(whole or "").strip()
        if len(whole) >= 2:
            variants.append(whole)
    for part in re.split(r"[;/|／]+", raw):
        part = part.strip()
        if len(part) >= 2:
            variants.append(part)

    for key in (_norm(name), _norm(name_en)):
        variants.extend(_COMMON_ALIASES.get(key, ()))

    return list(dict.fromkeys(v for v in variants if v))
