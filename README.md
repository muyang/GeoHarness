# GeoHarness v0.2.2

GeoNexus 的独立地理工作台。当前共享运行时使用 Python 服务与静态 Web UI，Platform 通过认证网关嵌入同一运行时；客户端和平台关联账号后，共享模型配置、对话、地图、执行记录与案例。

本次提交版本为 `v0.2.2`，Python 包与客户端版本均为 `0.2.2`。GIS 计算由 GeoNode 完成；GeoHarness 负责资源发现、安装、配置、交互与任务编排，兼容官方 MCP。

## v0.2.2 更新

本版将查看器通信改为 GeoLibre 3.3.0 官方 Widget 协议，按窗口、同源、requestId 与项目 seq 校验实际完成状态。嵌入 Platform 时加载平台共享 `/map/viewer` 组件；独立客户端继续使用官方 GeoLibre 查看器。地图范围参数遵循 `[west, south, east, north]`，保持既有模型、任务与案例接口。使用固定依赖和带哈希的查看器适配资源。

## 本版能力

- **产品市场 / 我的资源**：检索第三方 GeoNode 的 Data、Model、Skill、Workflow 等产品，检查声明、固定版本和权限后安装；默认 Platform 节点不可删除或改址。
- **第三方资源登记**：数据、算子、模型、算力描述符生成 GeoCard 与绑定；只有声明与连接配置进入客户端，远端数据和模型权重保持在节点。
- **可配置模型**：设置 API 服务地址、模型 ID、API Key，支持 OpenAI Chat Completions 兼容服务与本地兼容端点。空密钥保留现有值，显式清除才删除。
- **研究助手**：持久多轮对话、按需查询契约和地图上下文、逐步工具反馈；有依赖的任务最多八步，执行需要本轮明确授权。
- **GeoLibre 默认地图**：同源查看真实 GeoJSON、STAC 足迹与 GeoTIFF 像元，支持定位、图层动作、字段/选择摘要与撤销。
- **完整案例卡**：保存产品摘要、参数、依赖、来源、科学限制与产物哈希；锁定产品版本后复跑完整步骤。

仓库还保留原有 Vue 前端源码、测试与截图，其使用说明见 [README-v0.1.md](README-v0.1.md)。共享工作台使用下面的 Python 入口。

## 安装与启动

验证环境为 Python 3.12。需要提供匹配的已审核 SDK 源码，然后在本仓库根目录运行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e "/path/to/reviewed-sdk[mcp,server]"
.venv/bin/python -m pip install -e '.[geolibre,test]'
.venv/bin/geoharness --workspace /absolute/private-geoharness-workspace --port 8810
```

打开 `http://127.0.0.1:8810/`。默认监听本机回环地址。`workspace` 存储实际模型设置、连接凭据、安装记录、任务与产物，应该放在源码仓库外。

**依赖发布状态**：运行需要 SDK 的 `geonexus.registration` 等扩展接口。`GeoNexus-SDK` 当前远端 `main` 的 1.0.0 源码尚不含这些接口；仅安装该旧版本不能启动此共享运行时。本版 Python 声明要求 SDK 1.1 开发线，验证使用匹配的本地已审核源码。GeoKG / Platform 插件扩展也需要匹配的已审核版本，不能假定远端旧版本已兼容。SDK 与 GeoKG 的源码发布不在本标签范围内。

GeoLibre Viewer 使用 3.3.0；GeoNode WASI 算子执行器独立使用其审核版本。可选依赖版本见 [requirements-tested.txt](requirements-tested.txt)。运行真实案例还须连接有实际数据和执行能力的已授权 GeoNode；客户端安装不会启动远端算力或复制原始数据。

## 关联 Platform

1. 在设置页选择 Platform 地址并登录平台成员账号。
2. 点击“关联 Platform 账号”，进入同一成员工作空间。
3. 两端部署环境使用一致的私有 `GEONEXUS_HARNESS_GATEWAY_KEY`；配置 `GEONEXUS_PLATFORM_URL`，Platform 配置 `GEONEXUS_HARNESS_URL`。
4. 用户在设置界面配置自己的 LLM；新账号不会继承另一个账号的模型密钥。

调用签名、逐请求权限与产物所有权由网关验证。平台会话、节点令牌和模型密钥不会进入 URL、公开地图、案例卡或模型工具上下文。

## 使用流程

在产品市场搜索资源 → 查看契约和调用状态 → 明确授权后安装 → 配置输入 → 运行并查看逐步反馈 → 在地图查看成果或下载 → 保存完整案例并复跑。

香港局部 WorldPop 2020 与武汉 2020-12-25 Landsat NDVI 是固定真实案例，范围、时间、质量规则与哈希均由节点声明；结果不能外推为全市或当前年份结论。内置湿地产品使用固定随机种子的合成数据和演示模型，明确标记为 synthetic。

私有上传算子的案例需要重新提供输入；输入有生命周期，保存案例不等于永久保存原始私有文件。停止等待不保证取消已提交的远端计算。

## 源码与验证

| 目录 | 内容 |
| --- | --- |
| `src/geo_harness/` | Python 共享运行时、MCP 产品主机、模型对话、任务与地图服务 |
| `src/geo_harness/ui/` | 当前工作台静态 Web UI |
| `demo-products/` | 公开合成产品声明、案例与测试权重 |
| `tests/` | Python、地图确认与安全渲染回归 |
| `src/lib/`、`src/components/`、`test/` | 保留的 Vue 前端及原有测试 |

```sh
.venv/bin/python -m pytest tests -q
npm ci
node --test tests/test_map_viewport.cjs tests/test_dialogue_render.cjs
# 保留的 Vue 客户端测试
npm test
```

测试环境需匹配 SDK 与可选知识插件源码；实际验证范围及版本依赖应与发布记录一起查看，不把未启动的第三方服务报告为在线。

## 边界

实际 API Key、网关密钥、节点会话、运行数据库、私有 workspace 和用户文件不随本仓库发布。凭据文件采用本机私有文件权限，尚未集成系统钥匙串或静态加密。

产品安装校验清单、摘要、权限和锁定依赖；不会执行市场包中的任意 Python/JS 脚本。远端市场签名、生产多租户、多机调度与 DeepSeek Harness 适配仍待后续实现。


默认地图加载 GeoLibre 3.3.0 的官方资源，并使用 `src/geo_harness/ui/geo-viewer` 中带 MIT 许可与哈希清单的轻量适配器，默认选择 `maplibre-gl-raster`，修复投影 GeoTIFF 首次预览空白。平台与客户端由 Platform 的 `tools/build-geolibre-viewer.py` 同时生成适配文件；升级 GeoLibre 前需重新审核。已安装的官方包、MCP 与 Widget 接口保持原样。

## 与 RuoYi 控制面的验证

本版与 Platform 的官方RuoYi/PostgreSQL统一身份、GeoNode控制面联调。Platform是节点登记、启停和授权的唯一管理入口；客户端从平台公共目录读取已发布能力，运行前由SDK重新核验节点状态与授权。独立客户端和嵌入式工作台使用同一运行时。审核入口在本机为Platform `http://127.0.0.1:19315/`、GeoHarness `http://127.0.0.1:18816/`，端口以部署配置和启动器输出为准。

本地节点联调20项及重启后10项通过，包含目录/授权保留、执行审计幂等、共享工作台进入与退出撤销。完整生产多租户、负载与灾备验收尚未完成。更新客户端版本不升级GeoCard、产品manifest或插件自身的独立版本。
