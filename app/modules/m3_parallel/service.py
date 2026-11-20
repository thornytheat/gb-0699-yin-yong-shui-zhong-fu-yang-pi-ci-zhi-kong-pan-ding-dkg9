def execute(text):
    from app.pipeline import run
    result=run(text)
    return {"module":3, "report":result["reports"][2], "quarantine":result["quarantine"], "balance":result["balance"], "first_stats":result["first_stats"], "parallel":result["parallel"]}
