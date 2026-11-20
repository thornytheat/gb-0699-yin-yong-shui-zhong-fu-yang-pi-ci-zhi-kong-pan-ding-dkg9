import sqlite3, json, hashlib
from datetime import datetime, timezone
from app.config import DATA_DIR, RULE_VERSION
from app.errors import BusinessError
from app.pipeline import run, supplement_digest

def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"runs.sqlite", timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, decision TEXT NOT NULL DEFAULT '待复核', created TEXT NOT NULL)")
    columns={row["name"] for row in db.execute("PRAGMA table_info(runs)")}
    if "text" not in columns:
        db.execute("ALTER TABLE runs ADD COLUMN text TEXT NOT NULL DEFAULT ''")
    if "stats_revision" not in columns:
        db.execute("ALTER TABLE runs ADD COLUMN stats_revision INTEGER NOT NULL DEFAULT 0")
    db.execute("CREATE TABLE IF NOT EXISTS supplements (run_id TEXT NOT NULL, digest TEXT NOT NULL, text TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(run_id,digest))")
    db.execute("CREATE TABLE IF NOT EXISTS stats (run_id TEXT NOT NULL, revision INTEGER NOT NULL, first_stats TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(run_id,revision))")
    return db

def save(text, result):
    digest=hashlib.sha256((RULE_VERSION+"\n"+text).encode()).hexdigest()
    ident=digest[:16]
    payload=json.dumps(dict(result,rule_version=RULE_VERSION),ensure_ascii=False)
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,digest,result,text,created) VALUES(?,?,?,?,?)",(ident,digest,payload,text,datetime.now(timezone.utc).isoformat()))
        if db.execute("SELECT changes()").fetchone()[0]:
            db.execute("INSERT OR IGNORE INTO stats(run_id,revision,first_stats,created) VALUES(?,?,?,?)",(ident,0,json.dumps(result.get("first_stats",{}),ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
        else:
            # 旧库升级后原始输入为空，重跑同内容时回填，便于后续补传。
            db.execute("UPDATE runs SET text=? WHERE id=? AND text=''",(text,ident))
    return get(ident)

def _row(ident):
    with connect() as db:
        row=db.execute("SELECT * FROM runs WHERE id=?",(ident,)).fetchone()
    if row is None: raise BusinessError("NOT_FOUND","批次不存在",404)
    return row

def _decorate(row, db=None):
    item=dict(row);item.pop("text",None)
    item["result"]=json.loads(item["result"]);item["rule_version"]=item["result"].get("rule_version","2026.11.18.1")
    return item

def get(ident):
    return _decorate(_row(ident))

def history():
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT id,revision,decision,created FROM runs ORDER BY created DESC LIMIT 40")]

def supplement(ident, text):
    """补传首检记录。同一内容幂等；计算失败整体回滚，旧版统计保持不变。"""
    if not isinstance(text,str): raise BusinessError("TEXT","补传内容须为文本")
    digest=supplement_digest(text)
    now=datetime.now(timezone.utc).isoformat()
    with connect() as db:
        base=db.execute("SELECT text FROM runs WHERE id=?",(ident,)).fetchone()
        if base is None: raise BusinessError("NOT_FOUND","批次不存在",404)
        if db.execute("SELECT 1 FROM supplements WHERE run_id=? AND digest=?",(ident,digest)).fetchone():
            # 重试同一份补传：已有记录，不重复计入，也不产生新版本。
            return get(ident)
        if not base["text"]:
            raise BusinessError("BASE_TEXT","该批次缺少原始输入，无法补传",409)
        db.execute("INSERT INTO supplements(run_id,digest,text,created) VALUES(?,?,?,?)",(ident,digest,text,now))
        chunks=[{"digest":r["digest"],"text":r["text"]} for r in db.execute("SELECT digest,text FROM supplements WHERE run_id=? ORDER BY created",(ident,))]
        try:
            # 计算失败在事务内回滚，补传记录与统计一并撤销，旧版结果照常可读。
            result=run(base["text"],chunks)
        except Exception:
            db.rollback()
            raise
        revision=db.execute("SELECT stats_revision FROM runs WHERE id=?",(ident,)).fetchone()[0]+1
        # 新证据改变结论，此前复核失效：退回待复核并递增版本，旧客户端复核得到409。
        db.execute("UPDATE runs SET result=?,stats_revision=?,revision=revision+1,decision='待复核' WHERE id=?",(json.dumps(dict(result,rule_version=RULE_VERSION),ensure_ascii=False),revision,ident))
        db.execute("INSERT INTO stats(run_id,revision,first_stats,created) VALUES(?,?,?,?)",(ident,revision,json.dumps(result.get("first_stats",{}),ensure_ascii=False),now))
    return get(ident)

def review(ident,revision,decision):
    if not isinstance(decision,str) or decision not in {"通过","退回"}: raise BusinessError("DECISION","复核决定无效")
    current=get(ident)
    if decision=="通过" and current["result"].get("blocked"):
        raise BusinessError("BLOCKED","存在阻断项，请先修正数据",409)
    with connect() as db:
        changed=db.execute("UPDATE runs SET revision=revision+1,decision=? WHERE id=? AND revision=?",(decision,ident,revision)).rowcount
        if not changed: raise BusinessError("STALE","版本已更新，请刷新",409)
    return get(ident)

def supplements(ident):
    _row(ident)
    with connect() as db:
        return [{"digest":r["digest"],"created":r["created"]} for r in db.execute("SELECT digest,created FROM supplements WHERE run_id=? ORDER BY created",(ident,))]

def stats_history(ident):
    _row(ident)
    with connect() as db:
        return [{"revision":r["revision"],"first_stats":json.loads(r["first_stats"]),"created":r["created"]} for r in db.execute("SELECT * FROM stats WHERE run_id=? ORDER BY revision",(ident,))]
