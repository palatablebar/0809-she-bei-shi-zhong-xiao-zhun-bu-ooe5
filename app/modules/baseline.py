"""校准基准的身份。

一个业务组的基准就是它的同步点集合。基准版本只由同步点内容决定，
因此同一组同步点在任何批次里都会得到同一个版本号；换版意味着同步点
集合发生变化（例如晚到的同步数据补进来）。版本号用于在交接、页面和
证据里指认“这条读数依据哪一版基准”。
"""

from hashlib import sha256


def anchors(rows):
    """按设备 tick 升序返回同步点 (tick, source_ms)。"""
    return sorted(
        (row["ticks"], row["source_ms"]) for row in rows if row["kind"] == "sync"
    )


def canonical(points):
    return ";".join(f"{tick}:{source}" for tick, source in points)


def fingerprint(points):
    return sha256(canonical(points).encode("utf-8")).hexdigest()


def summary(points):
    """单个业务组的基准摘要。"""
    digest = fingerprint(points)
    return {
        "version": "BL-" + digest[:10].upper(),
        "fingerprint": digest,
        "anchors": len(points),
        "first_tick": points[0][0] if points else None,
        "last_tick": points[-1][0] if points else None,
    }


def version_of(summaries):
    """把 {业务组: 基准摘要} 合成为一版基准集合。"""
    parts = []
    for name, item in sorted(summaries.items()):
        item = item or {}
        token = item.get("fingerprint") or item.get("version") or "BL-UNKNOWN"
        parts.append(f"{name}={token}")
    digest = sha256(";".join(parts).encode("utf-8")).hexdigest()
    return {
        "version": "BS-" + digest[:10].upper(),
        "fingerprint": digest,
        "cases": len(summaries),
        "anchors": sum(int((item or {}).get("anchors") or 0) for item in summaries.values()),
    }
