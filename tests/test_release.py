import csv as csvlib
import io

import pytest

from app.business import DomainIssue
from app.intake.schema import HEADER
from app.modules.pipeline import run
from app.modules.release import decorate
from app.review.service import execute, review

BASE = [
    ["000101", "0001", "sync", "100", "160", "0", "交接明细"],
    ["000102", "0001", "reading", "150", "222", "4", "复核底稿"],
    ["000103", "0001", "sync", "200", "280", "0", "补录记录"],
    ["000104", "0001", "check", "0", "220", "0", "已对照来源"],
]
SECOND = [
    ["000201", "0002", "sync", "10", "40", "0", "交接明细"],
    ["000202", "0002", "sync", "20", "51", "0", "复核底稿"],
    ["000203", "0002", "reading", "15", "46", "0", "补录记录"],
    ["000204", "0002", "check", "0", "46", "0", "已对照来源"],
]
LATE_POINT = ["000105", "0001", "sync", "150", "221", "0", "晚到同步"]
SHIFTED_SECOND = [
    ["000201", "0002", "sync", "10", "40", "0", "交接明细"],
    ["000202", "0002", "sync", "20", "52", "0", "复核底稿"],
    ["000203", "0002", "reading", "15", "46", "0", "补录记录"],
    ["000204", "0002", "check", "0", "46", "0", "已对照来源"],
]
OUTSIDE_SECOND = [
    ["000201", "0002", "sync", "10", "40", "0", "交接明细"],
    ["000202", "0002", "sync", "15", "50", "0", "复核底稿"],
    ["000203", "0002", "reading", "25", "60", "0", "补录记录"],
    ["000204", "0002", "check", "0", "60", "0", "已对照来源"],
]


def source(*groups):
    stream = io.StringIO(newline="")
    writer = csvlib.writer(stream)
    writer.writerow(HEADER)
    for group in groups:
        writer.writerows(group)
    return stream.getvalue().encode()


def approve(store, data, note="首签记录"):
    item = execute(store, data)
    return review(store, item["id"], dict(revision=0, status="APPROVED", note=note))


def case(report, name):
    return next(item for item in report["cases"] if item["case"] == name)


def test_issued_reading_is_frozen_when_baseline_changes(store):
    first = approve(store, source(BASE))
    issued_value = case(first["report"], "0001")["measure"]["value"]
    issued_baseline = case(first["report"], "0001")["baseline"]["version"]

    # 晚到的同步点会把同一条读数插值成 221。
    report = execute(store, source(BASE + [LATE_POINT]))["report"]
    item = case(report, "0001")

    assert item["pinned"] is True
    assert item["measure"]["value"] == issued_value == 220
    assert item["baseline"]["version"] == issued_baseline
    assert item["delta"] == item["measure"]["value"] - item["measure"]["expected"]
    calibration = report["calibration"]
    assert calibration["previous_version"] == first["report"]["calibration"]["version"]
    change = next(c for c in calibration["changes"] if c["case"] == "0001")
    assert (change["previous"], change["value"]) == (220, 221)
    assert change["applied"] is False and change["pinned"] is True


def test_unreleased_scope_uses_new_baseline(store):
    approve(store, source(BASE))  # 只签发 0001
    report = execute(store, source(BASE, SHIFTED_SECOND))["report"]
    calibration = report["calibration"]

    assert calibration["affected"] == ["0002"]
    applied = next(c for c in calibration["changes"] if c["case"] == "0002")
    assert applied["applied"] is True and applied["pinned"] is False
    # 0001 冻结在旧基准，0002 用上新基准。
    assert (
        case(report, "0001")["baseline"]["version"]
        != case(report, "0002")["baseline"]["version"]
    )
    assert calibration["releasable"] is True


def test_unclosed_affected_scope_blocks_whole_version(store):
    first = approve(store, source(BASE))
    old_version = store.active()["version"]

    # 0002 在新基准下发生外推，尚未闭合：整版不可发布。
    candidate = execute(store, source(BASE, OUTSIDE_SECOND))
    calibration = candidate["report"]["calibration"]
    assert calibration["releasable"] is False
    assert any(item["case"] == "0002" for item in calibration["blocked"])

    with pytest.raises(DomainIssue, match="UNRESOLVED_ISSUES"):
        review(
            store,
            candidate["id"],
            dict(revision=0, status="APPROVED", note="试图整版发布"),
        )
    assert store.active()["version"] == old_version
    assert store.load(first["id"])["status"] == "APPROVED"


def test_changed_issued_source_is_blocked(store):
    approve(store, source(BASE))
    # 同一记录键 000102，但读数来源变了：不能当成普通重算。
    moved = [
        ["000101", "0001", "sync", "100", "160", "0", "交接明细"],
        ["000102", "0001", "reading", "150", "223", "4", "复核底稿"],
        ["000103", "0001", "sync", "200", "280", "0", "补录记录"],
        ["000104", "0001", "check", "0", "220", "0", "已对照来源"],
    ]
    report = execute(store, source(moved))["report"]
    assert any(
        item["reason"] == "ISSUED_SOURCE_CHANGED"
        for item in report["calibration"]["blocked"]
    )
    assert report["calibration"]["releasable"] is False


def test_failed_switch_keeps_old_version_and_data(store, monkeypatch):
    from contextlib import contextmanager

    first = approve(store, source(BASE))
    old_active = store.active()
    old_report = store.load(first["id"])["report"]
    old_issued = store.issued()

    candidate = execute(store, source(BASE + [LATE_POINT]))
    original = store.connect

    @contextmanager
    def broken():
        with original() as db:
            class Boom(Exception):
                pass

            class Proxy:
                def execute(_, sql, *args, **kwargs):
                    if "INSERT INTO releases" in sql:
                        raise Boom()
                    return db.execute(sql, *args, **kwargs)

                def __getattr__(_, name):
                    return getattr(db, name)

            yield Proxy()

    monkeypatch.setattr(store, "connect", broken)
    with pytest.raises(Exception):
        review(store, candidate["id"], dict(revision=0, status="APPROVED", note="切换失败"))
    monkeypatch.setattr(store, "connect", original)

    # 旧版本、旧数据、旧签发快照都还在，候选批次仍可复核。
    assert store.active()["version"] == old_active["version"]
    assert store.active()["readings"] == old_active["readings"]
    assert store.load(first["id"])["report"] == old_report
    assert store.issued() == old_issued
    assert store.load(candidate["id"])["status"] == "PENDING"


def test_decorate_is_pure_and_labels_every_baseline():
    raw = run(source(BASE, SECOND))
    clone = decorate(raw, {"version": None, "baseline": {}, "readings": {}}, {})
    assert "calibration" not in raw
    for item in clone["cases"]:
        assert item["baseline"]["version"].startswith("BL-")
        assert clone["calibration"]["inputs"][item["case"]] == item["baseline"]
    assert clone["calibration"]["issued"] == []
    assert clone["calibration"]["changes"] == []
    assert clone["calibration"]["releasable"] is True


def test_approved_batch_snapshot_never_rewritten(store):
    first = approve(store, source(BASE))
    frozen = store.load(first["id"])["report"]["calibration"]
    execute(store, source(BASE + [LATE_POINT]))  # 新基准到来
    again = store.load(first["id"])["report"]["calibration"]
    assert again == frozen


def test_stale_release_is_refused(store):
    approve(store, source(BASE))
    candidate = execute(store, source(BASE + [LATE_POINT]))
    approve(store, source(BASE, SECOND))  # 别处先推进了生效版本
    moved = store.active()["version"]

    with pytest.raises(DomainIssue, match="STALE_RELEASE"):
        store.approve(
            candidate["id"],
            0,
            "迟到的切换",
            "2026-01-02T00:00:00.000+00:00",
            candidate["report"],
        )
    assert store.active()["version"] == moved


def test_release_endpoint_lists_active_version(client):
    run = client.post("/api/runs", data={"sample": "clean"}).json
    client.patch(
        "/api/runs/" + run["id"],
        json=dict(revision=0, status="APPROVED", note="页面签发"),
    )
    output = client.get("/api/releases").json
    assert output["active"]["version"] == run["report"]["calibration"]["version"]
    assert output["active"]["run_id"] == run["id"]
    assert len(output["items"]) == 1


def test_switching_version_keeps_old_version_history(store):
    first = approve(store, source(BASE))
    old = store.active()
    second = execute(store, source(BASE + [LATE_POINT]))
    review(store, second["id"], dict(revision=0, status="APPROVED", note="换版签发"))

    history = {item["version"] for item in store.releases()}
    assert old["version"] in history and store.active()["version"] != old["version"]
    # 旧批次与旧签发快照仍可复核，断链风险不因换版发生。
    assert store.load(first["id"])["status"] == "APPROVED"
    assert ("0001", "000102") in store.issued()


def test_disappearing_case_blocks_release(store):
    approve(store, source(BASE))  # 签名覆盖 0001
    # 新一批只有 0002：0001 从活动版本里消失，复核链会断，整版阻断。
    report = execute(store, source(SECOND))["report"]
    assert any(
        item["case"] == "0001" and item["reason"] == "CASE_MISSING"
        for item in report["calibration"]["blocked"]
    )
    assert report["calibration"]["releasable"] is False


def test_replaced_reading_record_blocks_release(store):
    approve(store, source(BASE))
    # 同组同基准，但读数记录键换成 000106：原签发读数被顶掉。
    swapped = [
        ["000101", "0001", "sync", "100", "160", "0", "交接明细"],
        ["000106", "0001", "reading", "150", "222", "4", "复核底稿"],
        ["000103", "0001", "sync", "200", "280", "0", "补录记录"],
        ["000104", "0001", "check", "0", "220", "0", "已对照来源"],
    ]
    report = execute(store, source(swapped))["report"]
    assert any(
        item["reason"] == "ISSUED_RECORD_MISSING"
        for item in report["calibration"]["blocked"]
    )
    assert report["calibration"]["releasable"] is False


