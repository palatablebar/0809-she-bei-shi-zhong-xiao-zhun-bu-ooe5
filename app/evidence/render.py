import json

from app.modules.release import decorate


def artifact(run):
    report = run["report"]
    if "calibration" not in report:
        report = decorate(
            report, {"version": None, "baseline": {}, "readings": {}}, {}
        )
    calibration = report.get("calibration") or {}
    packet = {
        "schema": "review-evidence/1",
        "manifest": report["manifest"],
        "balance": report["balance"],
        "calibration": calibration,
        "cases": report["cases"],
        "intake": report["intake"],
        "review": {key: run[key] for key in ("status", "revision", "note", "reviewed")},
    }
    return (
        json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
