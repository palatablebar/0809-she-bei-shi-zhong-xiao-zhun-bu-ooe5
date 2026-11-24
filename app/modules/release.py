"""把一次计算整理成可发布的校准版本。

规则：
- 基准换版只作用于尚未签发的读数；未发布范围立即采用新基准。
- 已签发读数按记录键冻结，保留原值、原判定和原基准版本，不会被新基准
  悄悄改写。若按新基准重算会得到别的值，版本报告里如实列出这条差异，
  并标明“保持签发值”，交接时看得见但不会发生无声变化。
- 受影响且尚未闭合的未发布范围阻断整版，不做局部发布。
- 已签发读数的完整性同样要闭合：来源字段变了、记录键或业务组消失都会
  阻断，避免新读数悄悄顶掉旧签发。
- 版本报告的 previous_version 交给存储层，在一个事务里切换；切换失败
  旧版本及其数据原样保留。
"""

from app.modules.baseline import version_of
from app.modules.reconcile import balance as reconcile


def _computed(case):
    measure = case.get("measure")
    return dict(measure) if measure else None


def _value(measure):
    return (measure or {}).get("value")


def calibrate(report, previous, issued):
    """返回标注了基准与版本核对结果的新报告。

    previous: {"version", "baseline": {组: 摘要}, "readings": {组: 读数}}
    issued:   {(组, 读数记录键): 已签发快照}
    """
    previous = previous or {}
    issued = issued or {}
    prior_version = previous.get("version")
    prior_baseline = previous.get("baseline") or {}
    prior_readings = previous.get("readings") or {}

    changes, pinned, blocked, affected, applied, seen = [], [], [], [], [], set()
    inputs = {}

    for case in report.get("cases", []):
        name = case["case"]
        seen.add(name)
        record = case.get("reading")
        before = prior_baseline.get(name) or {}
        current = case.get("baseline") or {}
        # 该组来源数据带来的基准（换版后即为新基准），与“读数实际采用的
        # 基准”分开记录：冻结读数沿用旧基准，但版本本身要按数据基准推进，
        # 否则后续批次每次都会把同一组误判为又一次换版。
        inputs[name] = current
        changed = prior_version is not None and before.get("version") != current.get(
            "version"
        )
        recomputed = _computed(case)
        recomputed_status = case.get("status")

        # 已签发读数：按记录键冻结原值、原判定与原基准版本。
        snapshot = issued.get((name, record)) if record else None
        if snapshot:
            if (case.get("reading_source") or {}) != (snapshot.get("source") or {}):
                blocked.append(
                    dict(case=name, record=record, reason="ISSUED_SOURCE_CHANGED")
                )
            frozen = dict(snapshot.get("measure") or {})
            used_baseline = snapshot.get("baseline") or current
            case["baseline"] = used_baseline
            frozen["pinned"] = True
            case["measure"] = frozen
            case["status"] = snapshot.get("status")
            case["pinned"] = True
            # 判定差值跟着冻结后的值走，避免页面出现计算值与差值对不上。
            if "delta" in case and "value" in frozen and "expected" in frozen:
                case["delta"] = frozen["value"] - frozen["expected"]
            pinned.append(
                dict(
                    case=name,
                    record=record,
                    baseline=used_baseline.get("version"),
                    value=frozen.get("value"),
                )
            )
            # 差异可见但已签发值不变。已签发读数由签发闭合，不因换版
            # 重新判定是否可用；真正阻断的是下面未发布范围的闭合。
            if changed:
                affected.append(name)
                if _value(frozen) != _value(recomputed):
                    changes.append(
                        dict(
                            case=name,
                            record=record,
                            baseline_from=used_baseline.get("version"),
                            baseline_to=current.get("version"),
                            previous=_value(frozen),
                            value=_value(recomputed),
                            applied=False,
                            pinned=True,
                        )
                    )
            continue

        # 未发布范围：直接采用新基准。
        if not changed:
            continue
        affected.append(name)
        if recomputed is None or recomputed_status != "READY":
            blocked.append(
                dict(case=name, record=record, reason=recomputed_status or "UNMEASURED")
            )
            continue
        prior = prior_readings.get(name) or {}
        applied.append(name)
        changes.append(
            dict(
                case=name,
                record=record,
                baseline_from=before.get("version"),
                baseline_to=current.get("version"),
                previous=prior.get("value"),
                value=_value(recomputed),
                applied=True,
                pinned=False,
            )
        )

    # 上一版覆盖、这一版已不含的业务组：本版范围缩小，旧批次虽仍在，
    # 但活动版本的复核链会在该组断掉，视为无法闭合，阻断整版。
    dropped = []
    if prior_version is not None:
        dropped = sorted(set(prior_baseline) - seen)
        for name in dropped:
            blocked.append(dict(case=name, record=None, reason="CASE_MISSING"))

    # 已签发读数必须在同一业务组里仍以同一记录键出现：同组换了记录键、
    # 业务组消失或来源字段变了，都意味着原读数被顶掉，不能让新读数悄悄
    # 顶上旧签发。
    present = {
        (case["case"], case.get("reading"))
        for case in report.get("cases", [])
        if case.get("reading")
    }
    for name, record in sorted(issued):
        if name not in seen:
            if not any(item["case"] == name for item in blocked):
                blocked.append(dict(case=name, record=record, reason="CASE_MISSING"))
        elif (name, record) not in present:
            if not any(
                item["case"] == name and item["record"] == record for item in blocked
            ):
                blocked.append(
                    dict(case=name, record=record, reason="ISSUED_RECORD_MISSING")
                )

    used = {
        case["case"]: inputs.get(case["case"]) or case.get("baseline") or {}
        for case in report.get("cases", [])
    }
    if "balance" in report:
        report["balance"] = reconcile(report.get("intake") or {}, report.get("cases", []))
    baseline = version_of(used)
    # 只有跑完对账的整批才谈得上是否可发布；阶段预览不下这个结论。
    releasable = (
        bool((report.get("balance") or {}).get("releasable")) and not blocked
        if "balance" in report
        else None
    )
    report["calibration"] = {
        "version": baseline["version"],
        "baseline": baseline,
        "inputs": used,
        "previous_version": prior_version,
        "affected": affected,
        "applied": sorted(set(applied)),
        "dropped": dropped,
        "issued": pinned,
        "changes": changes,
        "blocked": blocked,
        "releasable": releasable,
    }
    return report


def decorate(report, previous, issued):
    """在副本上标注，避免改动已入库的原始计算结果。"""
    import copy

    return calibrate(copy.deepcopy(report), previous, issued)
