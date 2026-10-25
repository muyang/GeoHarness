# 共享运行时实施规格 v1（GeoHarness 0.2.9 × Platform v0.9.2）

> 状态：草案（T1 进行中）。本文件是 GeoHarness 共享运行时与 Platform 工作台协同的实施依据。
> 已确认的决策：① 子系统接口待沟通，先只定端口；② MapContext 含「当前激活工具 / 图层样式」；
> ③ 先接最基本 GIS 命令，按子系统需求补充配置；④ 接受冻结流程的模型漂移，记录并标注。

## 0. 定位

GeoHarness 是**共享运行时**（Python 服务 `:8810` + 静态 Web UI）。Platform 通过认证网关嵌入同一运行时；
独立客户端与 Platform 工作台共享账号、模型配置、对话、地图、执行记录与案例。
GIS 计算在 GeoNode / GeoLibre / RustGIS 本地命令完成；GeoHarness 负责发现、安装、配置、交互与编排。

两条硬约束：

1. **一套运行时**：两端只渲染同一运行时的 UI，不复制逻辑。
2. **三条同源**：同 `thread_id`、同 `MapContext`、同 `case/workflow` 目录。

## 1. MapContext v1

结构（示例）：

```json
{
  "thread_id": "t-abc", "revision": 42,
  "view": {"bbox": [89.7, -10.05, 140.8, 50.2], "crs": "EPSG:4326",
           "zoom": 5.4, "pitch": 0, "bearing": 0},
  "basemap": "satellite",
  "layers": [{
    "id": "rfi-sites", "name": "优先湿地站点", "type": "vector", "visible": true,
    "style": {"symbol": "circle", "ramp": "graduated", "field": "irreplaceability",
              "classBreaks": [0, 0.2, 0.5, 1.0],
              "palette": ["#0F9ED5", "#156082", "#C00000"]},
    "opacity": 0.9,
    "source": {"kind": "product", "ref": "geocard.eaaf.rfi-priority-sites"},
    "selected": true
  }],
  "selection": {"kind": "features", "ids": ["site-0091"], "geometry_hash": "sha256:…"},
  "active_tool": {"id": "terrain.slope", "state": "armed",
                  "params": {"method": "horn", "units": "degree"}},
  "time": {"mode": "range", "value": "2025-06-01/2025-08-31"}
}
```

- **传输**：增量 patch —— `{"base_revision": 41, "ops": [{"op": "replace", "path": "/view/bbox", "value": [...]}]}`；
  允许 `replace / add / remove`，路径必须以 `/view /basemap /layers /selection /active_tool /time` 开头；
  `add` 支持 `"-"` 追加到数组。200–500ms 防抖合并；`revision` 单调递增，缺口时客户端拉整包快照。
- **存储**：`<workspace>/map-context/<thread_id>.json`，`write_private`（0600、0700 目录）原子写；内存缓存可选。
- **注入**：`Workbench.context(for_model=True)` 内压缩为 ≤600 token 摘要（实现取 `max_chars=1200`）：
  视口/CRS、底图、可见图层（名称 + 样式字段/分级 + 不透明度）、选中、激活工具与参数、时间窗、`revision`。
  仅地图相关意图注入全量；其余意图只注入视口 + 选中。
- **确认门**：`active_tool.state = armed` 时返回确认卡（工具、参数、作用范围、预计耗时）；未确认不执行。
- **复现**：`Runtime.start` 时把当前 MapContext 快照写入 run record。

## 2. 命令适配（最小集 + 配置驱动）

先接 6 个基础命令；新增能力写入 `config/commands.yaml`，不改代码。

| command id | 类别 | 适配器 | 确认 |
|---|---|---|---|
| `geom.buffer` | 几何 | rustgis | 面积超阈值时 |
| `geom.clip` | 几何 | rustgis | 否 |
| `geom.dissolve` | 几何 | rustgis | 否 |
| `crs.reproject` | 坐标 | rustgis | 否 |
| `raster.zonal_stats` | 栅格 | node（GeoMCP） | 是 |
| `io.export_geojson` | 输出 | rustgis / node | 否 |

```yaml
- id: geom.buffer
  adapter: rustgis
  params_schema: {distance: {type: number, min: 0}, units: {enum: [m, km]}}
  output: geojson
  cost_weight: 0.5
  confirm: {when: area_gt, value: 5.0e9}
```

适配器接口：`discover(query) / describe(id) / execute(id, params, ctx) / cancel()`。
两种实现：`RustgisLocalAdapter`（WASM 优先、CLI 退化）、`GeoMCPAdapter`（远端节点，门禁/下推）。
对外统一 `skill_id` 命名空间，Agent 无感底层。

## 3. 子系统智能体端口（只定契约）

```python
class AgentAdapter(Protocol):
    def health(self) -> dict: ...
    def capabilities(self) -> dict: ...   # {name, domains, skills[], budget_hint}
    def task(self, envelope: dict) -> AsyncIterator[dict]: ...
    def cancel(self, task_id: str) -> None: ...
```

任务信封：`task_id / thread_id / parent_run_id / goal / context（page,map_context_revision,selection,case_id）/ budget / constraints`。
三种传输各留空实现（HTTP、MCP、私有 SDK），路由先用「规则 + 主代理兜底」，LLM 分类留开关。
一致性测试：必填字段、幂等（同 `task_id` 重放）、超时、错误码、取消。

## 4. 冻结策略与漂移

`Workflows.create(name, steps)` → `freeze()`：

```json
{"workflow_id": "wf-…", "version": 3, "steps": [...],
 "refs": {"$ref": "products[0].output"},
 "model": {"id": "deepseek-v3", "params": {"temperature": 0.2}, "prompt_hash": "sha256:…"},
 "resources": [{"product_id": "geocard.…", "digest": "sha256:…"}],
 "frozen_at": "2026-10-25T…", "signature": "sha256:…"}
```

执行：`start(identity, digest)` 校验资源 → `run(row)`；每步记录实际模型与参数 hash。
回放：比对决策分布/关键输出，超阈值标 `drift: true` 并附差异摘要，**不阻断**；案例页显示「冻结时模型 / 回放时模型」。

## 5. 预算

| 档 | 工具调用上限 | handoff | 确认 |
|---|---|---|---|
| Lite | 8 | 不允许 | 只读免确认 |
| Medium | 24 | 1 次 | 执行前确认 |
| Heavy | 60 | 多次 | 执行前 + 关键步确认 |

计数：`tool call`=1、`handoff`=1、本地命令=0.5。超限停止新调用、汇总已有结果、提示升档。

## 6. 任务分解

| 任务 | 落点 | 验收 |
|---|---|---|
| T1 MapContext | `map_context.py`、`workbench.py: context()`、`app.py` `/api/map-context` | 双端 revision 一致；摘要 ≤600 token；run 内可回看快照 |
| T2 命令适配 | `config/commands.yaml`、`commands/`、`workbench.action()` | 6 命令跑通；非法参数拒绝；确认落审计 |
| T3 路由与端口 | `agents/router.py`、`agents/adapters/*`、`tests/agents/conformance.py` | 契约测试过；30 条标注准确率 ≥90% |
| T4 冻结/回放/漂移 | `workflows.py` | 两次回放可对比；drift 可见 |
| T5 生产化 | `app.py` SSE 续传/幂等/限流、观测面板 | 断网 30s 恢复；并发 10；P95 < 8s |

## 7. 风险

1. 上下文注入成本 → 压缩 + 按意图注入。
2. 增量 patch 丢事件 → revision 缺口拉整包。
3. RustGIS 参数与 GeoCard 契约不一致 → 适配器层转换，契约以 GeoCard 为准。
4. 冻结流程跨模型漂移 → 记录 + 标注（已确认接受）。
5. 子系统接口未知 → 先落端口与契约测试。

## 8. 待确认

- `/api/map-context` 的路径与动词（GET 快照 / POST patch）。
- 地图侧上报频率（建议 200–500ms 防抖，仅 viewport/selection/active_tool 变化时）。
- 注入点是否直接改 `Workbench.context(for_model=True)`。
- run 启动时快照是否入 `run.json`。
- Platform `/map-viewer.html` 是否同步上报（跨仓任务）。
