from decimal import Decimal
import pytest
from app.errors import BusinessError
from app.pipeline import run
from app.modules.m3_parallel.rules import first_check, summarize
from app import store

HEADER = "id,batch,analyte,kind,pair,value,spike,unit,version"

BASE = "\n".join([
    HEADER,
    # P1：首检平行样缺失，只有复测 v2；当前按 v2 判定，首检待补
    "001S,B01,Pb,sample,P1,0.010,0,mg/L,1",
    "001D,B01,Pb,duplicate,P1,0.012,0,mg/L,2",
    # P2：整组首检未到
    "002S,B01,Pb,sample,P2,0.020,0,mg/L,1",
    # P3：首检齐全且通过
    "003S,B01,Pb,sample,P3,0.003,0,mg/L,1",
    "003D,B01,Pb,duplicate,P3,0.0035,0,mg/L,1",
    "003B,B01,Pb,blank,,0.0002,0,mg/L,1",
    # P4：首检齐全但失败
    "004S,B01,Pb,sample,P4,0.010,0,mg/L,1",
    "004D,B01,Pb,duplicate,P4,0.016,0,mg/L,1",
]) + "\n"

SUPPLEMENT_P1 = "\n".join([
    HEADER,
    "001D,B01,Pb,duplicate,P1,0.020,0,mg/L,1",
]) + "\n"


def unique(batch):
    return BASE.replace("B01", batch)


def supplement_for(batch):
    return SUPPLEMENT_P1.replace("B01", batch)


@pytest.fixture
def base_run():
    return run(BASE)


def pair(result, name):
    return next(row for row in result["parallel"] if row["pair"] == name)


def test_pending_when_first_duplicate_missing(base_run):
    row = pair(base_run, "P1")
    assert row["first_status"] == "PENDING"
    assert row["first_result"] == "待补"
    assert "平行样" in row["first_basis"]
    # 当下已有 v2 复测，放行仍按当前有效值，不被首检缺失拖成失败
    assert row["current_status"] == "PASS"
    assert row["current_duplicate_version"] == 2


def test_retest_value_does_not_stand_in_for_first():
    rows = [{"kind": "sample", "rev": 1, "value_mg": Decimal("0.010")},
            {"kind": "duplicate", "rev": 2, "value_mg": Decimal("0.010")}]
    assert first_check(rows)["status"] == "PENDING"


def test_summary_separates_pending_from_fail(base_run):
    stats = base_run["first_stats"]
    assert statistics_ok(stats)
    assert stats["pending"] == 2
    assert stats["pass"] == 1
    assert stats["fail"] == 1
    assert stats["total"] == 4
    assert stats["pass_rate"] == pytest.approx(0.25)
    assert stats["judged_pass_rate"] == pytest.approx(0.5)
    assert stats["coverage"] == pytest.approx(0.5)


def statistics_ok(stats):
    return stats["pass"] + stats["fail"] + stats["pending"] + stats["review"] == stats["total"]


def test_supplement_completes_group_and_rejudges(base_run):
    assert pair(base_run, "P1")["first_status"] == "PENDING"
    updated = run(BASE, [SUPPLEMENT_P1])
    row = pair(updated, "P1")
    assert row["first_status"] == "PAIR_FAIL"
    assert row["first_result"] == "失败"
    assert row["first_duplicate_version"] == 1
    # 晚到的首检只改变首检统计，当前有效值仍是最高版本 v2
    assert row["current_status"] == "PASS"
    assert updated["first_stats"]["pending"] == 1
    assert updated["first_stats"]["fail"] == 2


def test_duplicate_supplement_counted_once():
    once = run(BASE, [SUPPLEMENT_P1])
    twice = run(BASE, [SUPPLEMENT_P1, SUPPLEMENT_P1])
    assert once["first_stats"] == twice["first_stats"]
    assert len([q for q in twice["quarantine"] if q["reason"].startswith("SUPPLEMENT_")]) == 0


def test_store_retry_same_supplement_is_idempotent():
    saved = store.save(unique("B11"), run(unique("B11")))
    first = store.supplement(saved["id"], supplement_for("B11"))
    second = store.supplement(saved["id"], supplement_for("B11"))
    assert first["stats_revision"] == second["stats_revision"] == 1
    assert len(store.supplements(saved["id"])) == 1
    assert second["result"]["first_stats"]["pending"] == 1


def test_store_failed_supplement_keeps_old_statistics():
    saved = store.save(unique("B12"), run(unique("B12")))
    before = saved["result"]["first_stats"]
    with pytest.raises(BusinessError):
        store.supplement(saved["id"], "id,oops\n1,2\n")
    after = store.get(saved["id"])
    assert after["stats_revision"] == 0
    assert after["result"]["first_stats"] == before
    assert store.supplements(saved["id"]) == []


def test_store_stats_history_records_each_revision():
    saved = store.save(unique("B13"), run(unique("B13")))
    store.supplement(saved["id"], supplement_for("B13"))
    history = store.stats_history(saved["id"])
    assert [h["revision"] for h in history] == [0, 1]
    assert history[1]["first_stats"]["pending"] == 1


def test_supplement_invalidates_prior_review_revision():
    saved = store.save(unique("B15"), run(unique("B15")))
    reviewed = store.review(saved["id"], saved["revision"], "退回")
    updated = store.supplement(saved["id"], supplement_for("B15"))
    assert updated["revision"] == reviewed["revision"] + 1
    assert updated["decision"] == "待复核"
    with pytest.raises(BusinessError):
        store.review(saved["id"], reviewed["revision"], "退回")


def test_workbench_shows_buckets_and_basis():
    from fastapi.testclient import TestClient
    from app.main import app
    saved = store.save(unique("B14"), run(unique("B14")))
    page = TestClient(app).get(f"/module/3?run_id={saved['id']}").text
    assert "平行样首检通过率" in page
    for label in ("通过", "失败", "待补", "待复核"):
        assert label in page
    assert "首检判定依据" in page
    assert "首补" not in page
