from app.business import DomainIssue, measured


def compute(data):
    from bisect import bisect_right

    anchors, row, target = data
    tick = row["ticks"]
    i = bisect_right([a for a, _ in anchors], tick) - 1
    if i < 0 or tick > anchors[-1][0]:
        raise DomainIssue("OUTSIDE_SYNC")
    i = min(i, len(anchors) - 2)
    a, b = anchors[i]
    c, d = anchors[i + 1]
    span = c - a
    corrected = b + (2 * (tick - a) * (d - b) + span) // (2 * span)
    error = corrected - row["source_ms"]
    return measured(
        corrected,
        target,
        "毫秒",
        {"residual_ms": error, "before_tick": a, "after_tick": c},
        abs(error) > row["tolerance_ms"],
    )
