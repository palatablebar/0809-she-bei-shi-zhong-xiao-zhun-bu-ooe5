EXPECTED = {
    "0001": (2, 220, "READY"),
    "0002": (2, 46, "READY"),
    "0003": (2, None, "OUTSIDE_SYNC"),
    "0004": (2, 45, "OFFSET_LIMIT"),
}
EVIDENCE = {
    "0001": {"residual_ms": -2, "before_tick": 100, "after_tick": 200},
    "0002": {"residual_ms": 0, "before_tick": 10, "after_tick": 20},
}
