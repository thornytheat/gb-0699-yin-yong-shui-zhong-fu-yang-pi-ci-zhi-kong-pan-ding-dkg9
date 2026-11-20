# 接口

`POST /api/run`：{"text":"CSV内容"}。同规则版本与输入摘要只产生一条批次。

`GET/POST /api/1` 至 `/api/7`：独立样例或自定义文件计算。各模块返回 report、quarantine、balance。

`POST /api/review`：id、整数revision、decision取通过或退回。旧版本409；阻断项不能通过。

`POST /api/supplement`：{"id":"批次id","text":"首检补传CSV"}。迟到的首检记录并入该批次后整批重判，返回更新后的批次。同一内容重复提交（含网络重试）只计一次、不产生新统计版本；解析或计算失败返回422/409，旧版统计原样保留。

`GET /api/supplements/{id}`：已并入的补传摘要（digest、时间）。`GET /api/stats/{id}`：各统计版本的首检通过率快照，revision 0 为首发。

`GET /api/export/{id}`：唯一证据CSV，含 manifest、逐组首检/当前判定与隔离记录。`GET /health`：存活检查。

错误：结构/数值422，版本冲突409，不存在404，文件过大413。逐行异常进入quarantine。
