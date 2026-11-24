from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic

from app.business import DomainIssue
from app.config import RULE_VERSION
from app.modules.pipeline import run
from app.modules.release import decorate


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def present(store, run_id):
    """读取批次并按当前生效版本核对校准读数。

    已签发读数按记录键冻结，不会被后续换版改写；未发布范围采用新基准。
    版本核对结果只放在返回副本里，入库原文保持稳定。
    """
    record = store.load(run_id)
    report = record["report"]
    # 已签发的批次带着签发时的校准快照，任何新版生效后都原样返回，
    # 防止交接时被后来者悄悄改写。
    if record["status"] == "APPROVED" and "calibration" in report:
        return record
    record["report"] = decorate(report, store.previous(), store.issued())
    return record


def execute(store, data):
    start = monotonic()
    fingerprint = sha256(data).hexdigest()
    run_id = sha256(f"{RULE_VERSION}:{fingerprint}".encode()).hexdigest()
    try:
        store.load(run_id)
    except DomainIssue as error:
        if error.code != "RUN_NOT_FOUND":
            raise
        report = run(data)
        report["manifest"] = dict(
            sha256=fingerprint,
            version=RULE_VERSION,
            created=now(),
            duration_ms=round((monotonic() - start) * 1000, 3),
            bytes=len(data),
            run_id=run_id,
        )
        store.register(run_id, report)
    return present(store, run_id)


def review(store, run_id, values):
    if not isinstance(values, dict):
        raise DomainIssue("REVIEW_FIELDS")
    revision, status, note = (values.get(key) for key in ("revision", "status", "note"))
    if (
        type(revision) is not int
        or revision < 0
        or status not in ("APPROVED", "HELD")
        or not isinstance(note, str)
        or not (3 <= len(note.strip()) <= 200)
    ):
        raise DomainIssue("REVIEW_FIELDS")
    current = present(store, run_id)
    if revision != current["revision"]:
        raise DomainIssue("STALE_REVIEW")
    if current["status"] == "APPROVED":
        raise DomainIssue("RUN_FINALIZED")
    if status == "APPROVED":
        report = current["report"]
        if not report["balance"]["releasable"] or not report["calibration"]["releasable"]:
            raise DomainIssue("UNRESOLVED_ISSUES")
        store.approve(run_id, revision, note.strip(), now(), report)
    else:
        store.revise(run_id, revision, status, note.strip(), now())
    return present(store, run_id)
