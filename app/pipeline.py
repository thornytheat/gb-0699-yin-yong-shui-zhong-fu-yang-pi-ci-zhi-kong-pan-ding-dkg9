import hashlib
from pathlib import Path
from app.report import plain,reason_counts
from app.modules.m1_samples.rules import apply as stage1
from app.modules.m2_contract.rules import apply as stage2
from app.modules.m3_parallel.rules import apply as stage3
from app.modules.m4_spikes.rules import apply as stage4
from app.modules.m5_blanks.rules import apply as stage5
from app.modules.m6_release.rules import apply as stage6
from app.modules.m7_retest.rules import apply as stage7

def sample_text():
    return (Path(__file__).parent.parent/"sample_data"/"instrument.csv").read_text(encoding="utf-8-sig")

def supplement_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def normalize_supplements(supplements):
    """同一内容的重试补传只保留一份，避免重复计入。"""
    out=[];seen=set()
    for chunk in supplements or []:
        text=chunk["text"] if isinstance(chunk,dict) else chunk
        digest=chunk.get("digest") if isinstance(chunk,dict) else None
        digest=digest or supplement_digest(text)
        if digest in seen:continue
        seen.add(digest);out.append({"digest":digest,"text":text})
    return out

def run(text,supplements=()):
    supplements=normalize_supplements(supplements)
    ctx={"text":text,"supplements":supplements,"quarantine":[],"reports":[]}
    ctx["reports"].append(stage1(ctx))
    ctx["reports"].append(stage2(ctx))
    ctx["reports"].append(stage3(ctx))
    ctx["reports"].append(stage4(ctx))
    ctx["reports"].append(stage5(ctx))
    ctx["reports"].append(stage6(ctx))
    ctx["reports"].append(stage7(ctx))
    ctx.pop("text",None)
    ctx.pop("supplements",None)
    ctx["reasons"]=reason_counts(ctx)
    return plain(ctx)
