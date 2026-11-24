# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态。返回的每批都带 `report.calibration`：本版版本、生效版本、受影响业务组、本次变化的读数、冻结的已签发读数与阻断项。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。冲突返回 409，客户端读取新版本后重试。签发即发布本版校准版本：在单个事务里冻结已签发读数并切换生效版本；切换失败回滚，旧版本及其数据原样保留。生效版本已被他处推进时返回 409 `STALE_RELEASE`。

`GET /api/releases` 返回版本历史与当前生效版本（含各组基准与读数）。

`GET /api/runs/<id>/evidence` 下载内含运行清单、校准版本核对、行号隔离、业务证据和复核信息的 JSON。
