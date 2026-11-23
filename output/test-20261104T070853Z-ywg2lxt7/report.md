# 提测分析报告

仓库：/Users/jzttttt/JZT_WorkSpace/WorWorWorWorWork/互联网实习面试/TME实习文档/phone-agent-skill

比较基线：`7d75e66f2a5691b91c124e5381d12663aeb29762`

目标版本：`1c110d6e06af21a4853e2fab05d351800b44e859`

生成时间（UTC）：2026-11-04T07:08:53.311683+00:00

# 测试分析报告

## 1. 变更概览
本次提交聚焦于设备执行状态管理与 Web 跑批任务持久化：

- 在 `RunManager` 中新增按 `device_id` 的 `_active_runs` 设备占用表，并在 `create_run` / `_supervise` / 取消逻辑中统一释放设备锁。
- 在 Web API 中增加设备状态查询接口 `GET /api/devices/status`，并让 `GET /api/runs/busy`、`POST /api/runs` 与 `POST /api/runs/json` 支持按设备维度判断是否忙碌。
- 在 SQLite schema 与迁移逻辑中补充 `web_runs.device_id` 列与索引处理，确保旧库能平滑升级。
- 处理了数据库初始化时的重复初始化逻辑，避免异步初始化重复执行。

## 2. 关键代码审查结论
### 2.1 设备锁从“全局单值”改为“按设备字典”
风险点：
- 设备锁改成 `_active_runs: dict[str, str]` 后，所有接口都应该以 `device_id` 作为唯一键；`None` 设备 ID 需要单独禁止。
- 当前 `create_run` 里有 `if device_id in self._active_runs`，并在 `create_run` 与 `_supervise` 中都写入 `_active_runs[device_id] = run_id`，若异常退出时未进入 `finally`，可能导致设备永久占用。
- 代码中 `create_run_json` 与 `POST /api/runs` 已添加 device-aware 判断，但 `None` Upstream 可能尚未在所有入口统一拦截；例如 JSON 请求中 `device_id` 为空时仍可能进入 busy 判断。

### 2.2 旧数据库迁移兼容性
风险点：
- `web_run.py` 中 `device_id` 从 `index=True` 改为无索引，后续在 `migrate.py` 中手动 `CREATE INDEX IF NOT EXISTS ix_web_runs_device_id`。
- 该逻辑依赖 SQLite `sqlite_master` 查询；若表中已有同名索引、重跑 migration 时应无副作用，但若历史 schema 中索引名不同，筛选逻辑可能遗漏；用户需要确认旧数据的索引状态。
- `init_db.py` 中 `drop` 分支先 `drop_all` 再删除 SQLite 自定义索引，逻辑较复杂，若索引名称带引号/特殊字符或某些非标准对象存在，可能在某些环境上失败。

### 2.3 业务状态与 ADB 状态混用
`/api/devices/status` 返回了:
- `adb_status`: ADB 设备层状态
- `busy`: 业务层是否被任务占用
- `run_id`: 当前任务运行 ID

这是一种 UI 展示增强，风险是前端如果按 `busy` 与 `adb_status` 组合状态显示，需确认 `offline` 设备应如何处理，不要把离线设备误判为“非法忙碌”。

## 3. 需要优先验证的测试
### P0
1. 设备占用互斥：同一 `device_id` 在两个并发 `create_run` 请求中，第二个请求必须返回 409，且 `_active_runs` 中该设备只保留一个 `run_id`。
2. 任务正常结束后设备锁释放：一个 run 完成后，`run_manager._active_runs` 中对应 `device_id` 必须删除。
3. 任务取消后设备锁释放：调用 `cancel_run` 后，应释放对应设备，后续相同设备的新任务可创建。
4. 旧库升级：表中无 `device_id` 列时，应用启动或迁移时必须补列并创建索引，不抛 `OperationalError`。

### P1
5. `GET /api/runs/busy?device_id=xxx` 仅对指定设备返回状态，不应因为其他设备任务导致误报。
6. `GET /api/devices/status` 对离线设备返回 `busy=false` 且 `run_id=null`，不携带错误状态。
7. `list_runs(device_id=...)` 过滤逻辑必须同时覆盖内存中的 active run 和数据库中的历史记录。

### P2
8. `POST /api/runs/json` 在 `body.device_id` 为 `None` 时应返回 400，而不是走到 `run_manager.is_busy(None)` 引发误判。
9. `init_db(drop=True)` 在已存在自定义索引时应保持幂等，重复执行不应抛异常。

## 4. 结论
这次变更的核心价值在于“按设备控制并发执行”，确实修正了之前全局单任务锁的局限；但相应的风险集中在：
- 设备锁释放的幂等性与异常路径
- 历史 SQLite 数据迁移兼容性
- 接口参数校验的统一性

当前仓库中未发现与此逻辑对应的自动化测试文件，因此上述用例需要新增为回归测试，尤其是设备锁和迁移用例。

