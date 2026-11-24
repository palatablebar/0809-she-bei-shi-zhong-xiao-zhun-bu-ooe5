import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.business import DomainIssue

SCHEMA = """CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, report TEXT NOT NULL, created TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', revision INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '', reviewed TEXT
);
CREATE TABLE IF NOT EXISTS issued (
    case_id TEXT NOT NULL, record TEXT NOT NULL, run_id TEXT NOT NULL,
    baseline TEXT NOT NULL, source TEXT NOT NULL, measure TEXT NOT NULL,
    status TEXT NOT NULL, issued TEXT NOT NULL,
    PRIMARY KEY (case_id, record)
);
CREATE TABLE IF NOT EXISTS releases (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, version TEXT NOT NULL,
    baseline TEXT NOT NULL, readings TEXT NOT NULL, created TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0
);"""


def _dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Store:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.row_factory = sqlite3.Row
            db.executescript(SCHEMA)
            yield db

    def register(self, run_id, report):
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs(id,report,created) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING",
                (run_id, _dumps(report), report["manifest"]["created"]),
            )
        return self.load(run_id)

    def load(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise DomainIssue("RUN_NOT_FOUND")
        result = dict(row)
        result["report"] = json.loads(result["report"])
        return result

    def list(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,created,status,revision,note FROM runs ORDER BY created DESC,id LIMIT 50"
                )
            ]

    def issued(self):
        """已签发读数快照，键为 (业务组, 读数记录键)。"""
        with self.connect() as db:
            rows = db.execute("SELECT * FROM issued").fetchall()
        return {
            (row["case_id"], row["record"]): dict(
                run_id=row["run_id"],
                baseline=json.loads(row["baseline"]),
                source=json.loads(row["source"]),
                measure=json.loads(row["measure"]),
                status=row["status"],
                issued=row["issued"],
            )
            for row in rows
        }

    def active(self):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM releases WHERE active=1 ORDER BY created DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["baseline"] = json.loads(result["baseline"])
        result["readings"] = json.loads(result["readings"])
        return result

    def previous(self):
        """上一版（当前生效版本）的基准与读数，供本次换版核对。"""
        current = self.active()
        if current is None:
            return {"version": None, "baseline": {}, "readings": {}}
        return {
            "version": current["version"],
            "baseline": current["baseline"],
            "readings": current["readings"],
        }

    def releases(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,version,run_id,created,active FROM releases ORDER BY created DESC"
                )
            ]

    def revise(self, run_id, revision, status, note, now):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE runs SET status=?,note=?,reviewed=?,revision=revision+1 WHERE id=? AND revision=?",
                (status, note, now, run_id, revision),
            )
            if cursor.rowcount != 1:
                raise DomainIssue("STALE_REVIEW")
        return self.load(run_id)

    def approve(self, run_id, revision, note, now, report):
        """签发批次并把它的校准版本切为生效版本。

        全程在一个事务内：任一步失败都回滚，旧版本及其数据原样保留。
        已签发读数快照只增不改，旧记录键的复核链不会被换版覆盖。
        """
        calibration = report.get("calibration") or {}
        with self.connect() as db:
            # 先拿写锁，避免两个签发并发读到同一个生效版本后互相覆盖，
            # 造成已签发版本的发布记录丢失。
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise DomainIssue("RUN_NOT_FOUND")
            if row["revision"] != revision:
                raise DomainIssue("STALE_REVIEW")
            if row["status"] == "APPROVED":
                raise DomainIssue("RUN_FINALIZED")
            if not report.get("balance", {}).get("releasable") or not calibration.get(
                "releasable"
            ):
                raise DomainIssue("UNRESOLVED_ISSUES")
            current = db.execute(
                "SELECT version FROM releases WHERE active=1 LIMIT 1"
            ).fetchone()
            if (current["version"] if current else None) != calibration.get(
                "previous_version"
            ):
                raise DomainIssue("STALE_RELEASE")
            cursor = db.execute(
                "UPDATE runs SET status='APPROVED',note=?,reviewed=?,revision=revision+1 "
                "WHERE id=? AND revision=?",
                (note, now, run_id, revision),
            )
            if cursor.rowcount != 1:
                raise DomainIssue("STALE_REVIEW")
            for case in report.get("cases", []):
                record = case.get("reading")
                measure = case.get("measure")
                if not record or measure is None:
                    continue
                db.execute(
                    "INSERT INTO issued(case_id,record,run_id,baseline,source,measure,status,issued) "
                    "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(case_id,record) DO NOTHING",
                    (
                        case["case"],
                        record,
                        run_id,
                        _dumps(case.get("baseline") or {}),
                        _dumps(case.get("reading_source") or {}),
                        _dumps(measure),
                        case.get("status") or "",
                        now,
                    ),
                )
            baseline = dict(calibration.get("inputs") or {})
            if not baseline:
                baseline = {
                    case["case"]: case.get("baseline") or {}
                    for case in report.get("cases", [])
                }
            readings = {
                case["case"]: {
                    "record": case.get("reading"),
                    "value": (case.get("measure") or {}).get("value"),
                    "status": case.get("status"),
                    "pinned": bool(case.get("pinned")),
                }
                for case in report.get("cases", [])
            }
            db.execute("UPDATE releases SET active=0 WHERE active=1")
            db.execute(
                "INSERT INTO releases(id,run_id,version,baseline,readings,created,active) "
                "VALUES (?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET active=1,run_id=excluded.run_id",
                (
                    calibration["version"],
                    run_id,
                    calibration["version"],
                    _dumps(baseline),
                    _dumps(readings),
                    now,
                ),
            )
            # 把签发时的校准快照写回批次正文，交接与证据都以这一份为准，
            # 之后再有新版生效也不会改写这份记录。
            db.execute("UPDATE runs SET report=? WHERE id=?", (_dumps(report), run_id))
        return self.load(run_id)
