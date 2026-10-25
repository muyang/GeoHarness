# 共享运行时实施规格 v1（GeoHarness 0.2.9 × Platform v0.9.2）

> 状态：草案（T1 已接线；确认策略已落地为可配置）。本文件是 GeoHarness 共享运行时与 Platform 工作台协同的实施依据。
> 已确认的决策：① 子系统接口待沟通，先只定端口；② MapContext 含「当前激活工具 / 图层样式」；
> ③ 先接最基本 GIS 命令，按子系统需求补充配置；④ 接受冻结流程的模型漂移，记录并标注。

## 0. 定位

GeoHarness 是**共享运行时**（Python 服务 `:8810` + 静态 Web UI）。Platform 通过认证网关嵌入同一运行时；
独立客户端与 Platform 工作台共享账号、模型配置、对话、地图、执行记录与案例。
GIS 计算在 GeoNode / GeoLibre / RustGIS 本地命令完成；GeoHarness 负责发现、安装、配置、交互与编排。

两条硬约束：

1. **一套运行时**：两端只渲染同一运行时的 UI，不复制逻辑。
2. **三条同源**：同 `thread_id`、同 `MapContext`、同 `case/workflow` 目录。

## 1. MapContext v1（复用现有来源，不建独立存储）

**实现决策（2026-10-25）**：地图状态只有一个来源 —— `Workbench.state` / `Workbench.context()`。
本版不建独立 MapContext 存储（曾写过一版，已删）：`context()` 增加 `layers[].style` 与派生的
`active_tool`（取最后一条 `pending` 地图动作），模型侧只通过纯函数 `map_context.model_view()` 裁剪
（层数/字段/待确认动作上限），并在 `chat()` 的 `<map_context>` 注入与 `map_context` 工具里统一使用；
任务提交时把 `model_view(context)` 写入任务记录，案例已按同样方式快照。

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

## 1.1 确认策略（已实现，可配置）

阈值存在工作区设置 `confirm` 块里，后台可改（`GET/POST /api/settings` 的 `confirm` 字段）：

```json
{"enabled": true, "actions": ["layer.remove", "result.open"],
 "extent_area_gt": 5000000000, "raster_pixels_gt": 100000000}
```

- 判定是纯函数 `policy.decide(action, args, confirm)`：命中 `actions`、或 bbox 面积超过 `extent_area_gt`、
  或显式 `raster_pixels` 超过 `raster_pixels_gt` 时报 `needs=true` 并给出原因；
- 当前为**提示性**：判定随地图动作返回（`row.confirmation`），**不硬拦**——因为现有 UI 与案例大范围
  （候鸟案例 bbox 约 3.6e13 m²）会必然触发；强制范围待定（见 §8）。
- 默认值：`extent_area_gt = 5e9 m²`、`raster_pixels_gt = 1e8`（可配置）。

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

## 8. 案例基线（已核实，2026-10-25）

- Platform **v0.9.2 的示范案例是 `durham.case.transit-equity`**（Durham 公交公平性）：
  案例包在 `public-products/cases/durham-transit-equity/`（geocard/lock/baseline/manifest），
  由 `services/v02/case_stories.py` 从 `public-products/cases` 读取并经 `integration.py` 挂载；
  README 有 Durham 专章，说明见 `docs/DURHAM_CASE_STORY.md`。规模：68 tracts / 22 interventions /
  332,353 人口 / 840 站点 / 6 步真实执行 / 七章地图故事。
- **候鸟-湿地案例不是 v0.9.2 的发布案例**：仓库里只有 `uploads/cases/flightway/*.csv`（上传夹具）
  与 `docs/flightway-case-demo.md`（教学文档，自述数据为合成）。本地 `data/geonexus.db` 里的
  `case-eaaf-wetland-priority` 属**未跟踪的开发数据**（`.gitignore` 含 `*.db`），重置代码不会更新它。
- 对确认策略的影响：Durham 几何 bbox `[-79.0163, 35.8632, -78.6993, 36.2393]`，面积约
  **1.19e9 m²（~1194 km²）**，低于 5e9 m² 阈值 —— 官方示范案例不会被阈值误触发。
- 后续验证与截图**以 Durham 为基准案例**，不再使用本地旧 wetland 数据。

## 9. 验证记录（2026-10-25，已按用户决定冻结在当前层级）

用户决定：接受「包 + 服务 + 平台测试」验证层级；浏览器 `/cases` 截图留到部署环境。

**已完成**
- Durham 案例包：`manifest` 通过 `services/v02/solution-case.schema.json`；文件 SHA-256 与 manifest 一致；
  68 tracts / 22 interventions / 332,353 人口 / 840 站点 / **6 步全部 succeeded**；输出 rankings 数 = interventions。
- SDK 兼容层（以 released v1.1.0 为基线，分支 `release/1.1.1`，提交 `8988515`）：
  - `geonexus.geocard.contracts`（ContractRequest/Report/ResultManifest/validate_contract），7 项单测；
  - `create_mcp_server(server, http_guarded=False)` 返回 GeoMCPBridge（进程内 `call_tool`），2 项单测；
  - 规则由平台测试反推，**需 SDK 负责人评审**（尤其 no-export 策略与 http_guarded 语义）。
- 平台 `services/v02` 用该 SDK **启动成功**；`services/v02/test_case_stories.py` **6/6 通过**。

**未做（留待部署环境）**
- 浏览器 `/cases` 的 Durham 截图：案例可见性依赖节点目录发布 `durham.case.transit-equity` 及其组件卡
  （`durham.data.*` 不在仓库，属于发布节点），需要 Java 控制面 + Postgres + 节点栈。

**结论**
- 仓库层面的 v0.9.2 × SDK v1.1.0 兼容性问题已消除（两个缺失 API 已补齐并测试）；
- 端到端 UI 验收不在本地伪造，部署环境再补。

## 10. 待确认

- 地图侧上报频率（沿用现有 `sync`，建议 200–500ms 防抖）。
- ~~注入点~~：已确认复用 `context(for_model=True)` + `model_view()`。
- ~~任务快照~~：已在 `submit` 记录写入 `map_context`（待确认是否也写入 `Runtime.start` 的 demo run）。
- Platform `/map-viewer.html` 是否同步上报（跨仓任务）。
