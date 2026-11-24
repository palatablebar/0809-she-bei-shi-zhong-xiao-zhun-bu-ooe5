"""定位每个业务组用于校准的那一条读数。"""


def reading(rows):
    found = [row for row in rows if row["kind"] == "reading"]
    return found[0] if len(found) == 1 else None


def record(rows):
    row = reading(rows)
    return row["record"] if row else None


def source(rows):
    """读数自身的来源字段。

    已签发读数按记录键冻结；若同一记录键的来源字段发生变化，就不再是
    原来那条读数，必须在版本里显式拦下，不能当作新基准下的普通重算。
    """
    row = reading(rows)
    if row is None:
        return None
    return {key: row[key] for key in ("record", "case", "ticks", "source_ms", "tolerance_ms")}
