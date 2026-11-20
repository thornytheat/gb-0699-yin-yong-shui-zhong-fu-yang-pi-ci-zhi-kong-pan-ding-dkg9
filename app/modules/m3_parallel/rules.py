"""平行样首检与当前有效值判定。

首检证据只取版本 1 的原始记录；复测（version>=2）只更新当前有效值，
不能顶替首检。当前有效值取 batch+analyte+id 身份内最高版本，放行按当前值。
首检记录未到（或同一侧出现多条版本 1 记录）时该组记为“待补”，
既不按合格推断，也不当作失败。
"""
from decimal import Decimal
from app.report import report
from app.numbers import fmt

MDL = Decimal("0.001")
KINDS = {"sample", "duplicate"}
LABELS = {
    "PASS": "通过",
    "PAIR_FAIL": "失败",
    "PAIR_MISSING": "失败",
    "CENSORED_REVIEW": "待复核",
    "PENDING": "待补",
}
SIDE_NAME = {"sample": "原样", "duplicate": "平行样"}


def pair_check(a, b, mdl=MDL, censored=False):
    if censored:return {"status":"CENSORED_REVIEW","metric":None,"limit":None,"method":"限定值"}
    mean=(a+b)/2;diff=abs(a-b)
    if mean<5*mdl:return {"status":"PASS" if diff<=mdl else "PAIR_FAIL","metric":diff,"limit":mdl,"method":"绝对差mg/L"}
    relative=diff/mean
    return {"status":"PASS" if relative<=Decimal("0.20") else "PAIR_FAIL","metric":relative,"limit":Decimal("0.20"),"method":"相对偏差"}


def first_evidence(rows):
    """挑出首检证据（版本 1），按原样/平行样各取唯一一条。"""
    evidence = {"sample": None, "duplicate": None, "missing": [], "conflict": []}
    for kind in ("sample", "duplicate"):
        candidates = [r for r in rows if r["kind"] == kind and r["rev"] == 1]
        if len(candidates) == 1:
            evidence[kind] = candidates[0]
        elif not candidates:
            evidence["missing"].append(kind)
        else:
            evidence["conflict"].append(kind)
    return evidence


def first_check(rows):
    """按首检证据判定；证据未齐时返回待补，绝不拿复测值冒充首检。"""
    evidence = first_evidence(rows)
    if evidence["missing"] or evidence["conflict"]:
        parts = []
        if evidence["missing"]:
            parts.append("缺" + "、".join(SIDE_NAME[k] for k in evidence["missing"]))
        if evidence["conflict"]:
            parts.append("多份" + "、".join(SIDE_NAME[k] for k in evidence["conflict"]))
        return {
            "status": "PENDING", "metric": None, "limit": None, "method": "首检",
            "reason": "首检记录未齐（" + "；".join(parts) + "），暂不判定", "evidence": evidence,
        }
    sample, duplicate = evidence["sample"], evidence["duplicate"]
    check = pair_check(sample["value_mg"], duplicate["value_mg"], censored=sample["censored"] or duplicate["censored"])
    return dict(check, reason=None, evidence=evidence)


def current_check(rows):
    """当前有效值：版本最高的一条原样 + 一条平行样。"""
    left = [r for r in rows if r["kind"] == "sample"]
    right = [r for r in rows if r["kind"] == "duplicate"]
    if len(left) != 1 or len(right) != 1:
        return {"status": "PAIR_MISSING", "metric": None, "limit": None, "method": "配对"}, None, None
    check = pair_check(left[0]["value_mg"], right[0]["value_mg"], censored=left[0]["censored"] or right[0]["censored"])
    return check, left[0], right[0]


def _evidence(row, side):
    prefix = f"first_{side}_"
    if row is None:
        return {prefix + "id": None, prefix + "version": None, prefix + "value_mg": None,
                prefix + "line": None, prefix + "source": None}
    return {
        prefix + "id": row["id"],
        prefix + "version": row["rev"],
        prefix + "value_mg": row["value_mg"],
        prefix + "line": row.get("source_line", row["line"]),
        prefix + "source": row.get("source", "首发"),
    }


def _values(sample, duplicate):
    return f"{sample['id']} v{sample['rev']}={sample['value_mg']}、{duplicate['id']} v{duplicate['rev']}={duplicate['value_mg']}"


def _basis(label, check, sample, duplicate):
    if check["status"] == "PENDING":
        return check["reason"]
    if check["status"] == "PAIR_MISSING":
        return f"{label}缺少原样或平行样，无法判定"
    values = _values(sample, duplicate)
    if check["status"] == "CENSORED_REVIEW":
        return f"{label} {values} 含限定值，需人工复核"
    op = "≤" if check["status"] == "PASS" else ">"
    return f"{label} {values}，{check['method']} {fmt(check['metric'])} {op} {fmt(check['limit'])}"


def summarize(records):
    total = len(records)
    passed = sum(r["first_status"] == "PASS" for r in records)
    failed = sum(r["first_status"] == "PAIR_FAIL" for r in records)
    pending = sum(r["first_status"] == "PENDING" for r in records)
    review = sum(r["first_status"] == "CENSORED_REVIEW" for r in records)
    judged = passed + failed
    return {
        "total": total,
        "pass": passed,
        "fail": failed,
        "pending": pending,
        "review": review,
        "judged": judged,
        # 交班口径：通过 / 全部平行组。待补单列，不并入失败，也不从分母抹掉。
        "pass_rate": passed / total if total else 0.0,
        # 待补补齐前通过率的可能区间（下限=待补全不通过，上限=待补全通过）。
        "rate_low": passed / total if total else 0.0,
        "rate_high": (passed + pending) / total if total else 0.0,
        # 备查口径：只算已判定组。待补多时该值会偏高，不能当交班口径。
        "judged_pass_rate": passed / judged if judged else 0.0,
        "coverage": judged / total if total else 0.0,
    }


def apply(ctx):
    history = [r for r in ctx.get("normalized", []) if r["kind"] in KINDS]
    groups = {}
    for r in history:
        groups.setdefault((r["batch"], r["analyte"], r["pair"]), []).append(r)
    effective = {}
    for r in ctx["effective"]:
        if r["kind"] in KINDS:
            effective.setdefault((r["batch"], r["analyte"], r["pair"]), []).append(r)

    out = []
    for key in sorted(groups):
        check, left, right = current_check(effective.get(key, []))
        first = first_check(groups[key])
        sample, duplicate = first["evidence"]["sample"], first["evidence"]["duplicate"]
        record = {
            "batch": key[0], "analyte": key[1], "pair": key[2],
            "left": left["value_mg"] if left else None,
            "right": right["value_mg"] if right else None,
        }
        record.update(check)
        record.update({
            "current_status": check["status"],
            "current_result": LABELS.get(check["status"], check["status"]),
            "current_basis": _basis("当前", check, left, right),
            "current_sample_version": left["rev"] if left else None,
            "current_duplicate_version": right["rev"] if right else None,
            "first_status": first["status"],
            "first_result": LABELS.get(first["status"], first["status"]),
            "first_metric": first["metric"],
            "first_limit": first["limit"],
            "first_method": first["method"],
            "first_reason": first["reason"],
            "first_basis": _basis("首检", first, sample, duplicate),
        })
        record.update(_evidence(sample, "sample"))
        record.update(_evidence(duplicate, "duplicate"))
        out.append(record)

    summary = summarize(out)
    ctx["parallel"] = out
    ctx["first_stats"] = summary
    return report(out, 配对=len(out), 失败=sum(r["status"] != "PASS" for r in out),
                  首检通过=summary["pass"], 首检失败=summary["fail"],
                  首检待补=summary["pending"], 首检待复核=summary["review"],
                  首检通过率=f"{summary['pass_rate'] * 100:.2f}%")
