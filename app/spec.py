COLUMNS = ("ticks", "source_ms", "tolerance_ms")
KINDS = ("sync", "reading", "check")
PROJECT = {
    "name": "设备时钟校准簿",
    "actor": "工厂数据采集工程师",
    "stages": [
        ("intake", "样例采信"),
        ("prepare", "同步点校核"),
        ("calculate", "漂移插值"),
        ("policy", "误差审查"),
        ("balance", "运行对账"),
    ],
    "chart": "参考时钟",
}
