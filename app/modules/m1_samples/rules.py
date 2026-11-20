from app.reader import read_rows
from app.report import report,quarantine
FIELDS="id batch analyte kind pair value spike unit version".split()

def _accept(ctx, rows, seen, source="首发"):
    out=[]
    for r in rows:
        r=dict(r,source=source)
        key=(r["batch"],r["analyte"],r["id"],r["version"])
        if not r["id"]:quarantine(ctx,r,"ID_REQUIRED");continue
        if key in seen:quarantine(ctx,r,"VERSION_CONFLICT");continue
        seen.add(key);out.append(r)
    return out

def apply(ctx):
    rows,bad,blank=read_rows(ctx["text"],FIELDS);ctx["quarantine"].extend(bad);ctx["blank_rows"]=blank
    seen=set();out=_accept(ctx,rows,seen)
    accepted,rejected,empty=len(rows),len(bad),blank
    supplements=[]
    for chunk in ctx.get("supplements",[]):
        learned,bad,blank=read_rows(chunk["text"],FIELDS)
        label="补传"+chunk["digest"][:8]
        supplements.append({"digest":chunk["digest"],"label":label,"rows":len(learned),"quarantined":len(bad),"blank":blank})
        for r in bad:
            r=dict(r,source=label);quarantine(ctx,r,"SUPPLEMENT_"+r["reason"])
        out.extend(_accept(ctx,learned,seen,label))
        accepted+=len(learned);rejected+=len(bad);empty+=blank
    ctx["supplement_accounting"]=supplements
    ctx["input_count"]=accepted+rejected+empty
    ctx["raw"]=out;return report(out,样品=len(out),隔离=len(ctx["quarantine"]))
