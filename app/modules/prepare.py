from app.business import DomainIssue, by_kind, prepared, single


def prepare(rows):
    anchors = sorted((r["ticks"], r["source_ms"]) for r in by_kind(rows, "sync"))
    if len(anchors) < 2 or any(
        a >= c or b >= d for (a, b), (c, d) in zip(anchors, anchors[1:])
    ):
        raise DomainIssue("SYNC_ORDER")
    return prepared(
        len(anchors),
        {"first_tick": anchors[0][0], "last_tick": anchors[-1][0]},
        (anchors, single(rows, "reading"), single(rows, "check")["source_ms"]),
    )
