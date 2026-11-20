import csv,io,json

def evidence_csv(run):
    out=io.StringIO();writer=csv.writer(out)
    result=run["result"]
    writer.writerow(["run_id","sha256","rule_version","kind","line","reason","evidence"])
    writer.writerow([run["id"],run["digest"],run["rule_version"],"manifest","","",json.dumps({"balance":result["balance"],"decision":run["decision"],"revision":run["revision"],"first_stats":result.get("first_stats",{})},ensure_ascii=False)])
    for row in result.get("parallel",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"first_inspection",row.get("first_sample_line",""),row.get("first_status",""),json.dumps({k:row.get(k) for k in ("batch","analyte","pair","first_result","first_basis","current_result","current_basis","first_sample_id","first_sample_version","first_duplicate_id","first_duplicate_version","current_sample_version","current_duplicate_version")},ensure_ascii=False)])
    for row in result.get("final",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"result",row.get("line",""),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    for row in result.get("quarantine",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"quarantine",row.get("line",""),row["reason"],json.dumps(row,ensure_ascii=False)])
    return "\ufeff"+out.getvalue()
