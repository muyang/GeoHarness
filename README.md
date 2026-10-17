# GeoHarness v0.2.9

GeoNexus 的独立地理工作台。当前共享运行时使用 Python 服务与静态 Web UI，Platform 通过认证网关嵌入同一运行时；客户端和平台关联账号后，共享模型配置、对话、地图、执行记录与案例。

本次提交版本为 `v0.2.9`，Python 包与客户端版本均为 `0.2.9`。源码同步至 [muyang/GeoHarness](https://github.com/muyang/GeoHarness) 与 [GeoNexus-Team/GeoHarness](https://github.com/GeoNexus-Team/GeoHarness)。GIS 计算由 GeoNode 完成；GeoHarness 负责资源发现、安装、配置、交互与任务编排，兼容官方 MCP。

## v0.2.9 更新

### 统一账号与共享工作台

打开 [GeoHarness 登录](http://127.0.0.1:8810/login)，输入已有 Platform 用户名或邮箱与密码。客户端固定连接 [Platform](http://127.0.0.1:3301/)，不新建用户表。首次升级时旧访问令牌可能已过期，需要重新登录一次；之后保存可轮换的刷新会话，访问失效时向 Platform 续期。禁用、改密或撤销会话后不能继续打开该工作空间。

同一账号的模型、对话、地图、任务与案例仍使用原目录。已有模型配置不被覆盖；只有明确勾选且该账号未配置模型时，才迁入本机旧模型。右上角“退出登录”清除客户端会话并返回登录页，保留账号数据，也不注销 Platform 浏览器会话。同一本机运行时一次关联一个客户端账号。

刷新令牌仅保存在权限为 0600 的 `private-platform-session.json`，不进入浏览器返回、模型上下文、产品包或 Git。原本将身份错误包装成“未返回有效 JSON”的问题已修复，连接失败、错误入口、身份过期和权限不足分别反馈。

统一启动使用 `--require-login`，关闭旧的未绑定账号 API；退出后无法继续通过根地址读取模型设置或调用助手。仅在明确的离线开发场景，不带此参数启动时才保留本机旧 API 兼容模式。

桌面框架源码采用同一套界面与运行时，当前未交付已签名安装包。见 [桌面预览与打包](desktop/README.md)。本阶段不把 Java、数据库和 GIS 依赖复制进桌面包；完整离线安装、系统钥匙串、代码签名和自动更新属于后续交付。

本版将查看器通信改为 GeoLibre 3.3.0 官方 Widget 协议，按窗口、同源、requestId 与项目 seq 校验实际完成状态。嵌入 Platform 时加载平台共享 `/map/viewer` 组件；独立客户端继续使用官方 GeoLibre 查看器。地图范围参数遵循 `[west, south, east, north]`，保持既有模型、任务与案例接口。使用固定依赖和带哈希的查看器适配资源。

本次版本号按演示发布线指定为 **v0.2.9**；历史 v0.3 标签保留。新增统一深浅主题、Platform 风格底图、地图视图恢复，以及产品市场调用时自动注入 GeoLibre 内部会话。已安装产品仍须具有当前有效的调用授权，外部节点契约发生变化仍要求重新确认安装。

## 本版能力

- **产品市场 / 我的资源**：检索第三方 GeoNode 的 Data、Model、Skill、Workflow 等产品，检查声明、固定版本和权限后安装；默认 Platform 节点不可删除或改址。
- **第三方资源登记**：数据、算子、模型、算力描述符生成 GeoCard 与绑定；只有声明与连接配置进入客户端，远端数据和模型权重保持在节点。
- **可配置模型**：设置 API 服务地址、模型 ID、API Key，支持 OpenAI Chat Completions 兼容服务与本地兼容端点。空密钥保留现有值，显式清除才删除。
- **研究助手**：持久多轮对话、按需查询契约和地图上下文、逐步工具反馈；有依赖的任务最多八步，执行需要本轮明确授权。
- **GeoLibre 默认地图**：同源查看真实 GeoJSON、STAC 足迹与 GeoTIFF 像元，支持定位、图层动作、字段/选择摘要与撤销。
- **完整案例卡**：保存产品摘要、参数、依赖、来源、科学限制与产物哈希；锁定产品版本后复跑完整步骤。

旧版 Vue 客户端已从当前代码中移除，可通过 Git 历史查看；当前唯一客户端入口为下方 Python 服务及 `src/geo_harness/ui/` 静态界面。`package.json` 仅为共享界面浏览器回归测试安装 jsdom。

## 安装与启动

验证环境为 Python 3.12。需要提供匹配的已审核 SDK 源码，然后在本仓库根目录运行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e "/path/to/reviewed-sdk[mcp,server]"
.venv/bin/python -m pip install -e '.[geolibre,test]'
.venv/bin/geoharness --workspace /absolute/private-geoharness-workspace --port 8810
```

打开 `http://127.0.0.1:8810/`。默认监听本机回环地址。`workspace` 存储实际模型设置、连接凭据、安装记录、任务与产物，应该放在源码仓库外。

**依赖发布状态**：运行需要 SDK 的 `geonexus.registration` 等扩展接口。请确认所用 SDK 包含 `geonexus.registration`、MCP 与 GeoNode 扩展接口；不包含这些接口的旧 SDK 不能启动此共享运行时。本版 Python 声明要求 SDK 1.1 开发线，验证使用匹配的本地已审核源码。GeoKG / Platform 插件扩展也需要匹配的已审核版本，不能假定远端旧版本已兼容。SDK 与 GeoKG 的源码发布不在本标签范围内。

GeoLibre Viewer 使用 3.3.0；GeoNode WASI 算子执行器独立使用其审核版本。可选依赖版本见 [requirements-tested.txt](requirements-tested.txt)。运行真实案例还须连接有实际数据和执行能力的已授权 GeoNode；客户端安装不会启动远端算力或复制原始数据。

## 关联 Platform

1. 打开 `/login`，使用已有 Platform 用户名或邮箱登录。统一部署固定连接 `http://127.0.0.1:3301/`，不提供浏览器任意改址。
2. 进入同一账号工作空间；设置页兼容入口也会引导统一登录。
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
| `package.json`、`package-lock.json` | 静态工作台浏览器测试依赖，非第二套客户端 |

```sh
.venv/bin/python -m pytest tests -q
npm ci
npm test
```

历史验证（2026-10-16）：本机通过 177 项 Python 测试与 10 项界面/桌面边界测试；构建的 wheel 包含登录页、地图查看器与版本 0.3.0 元数据。

测试环境需匹配 SDK 与可选知识插件源码；实际验证范围及版本依赖应与发布记录一起查看，不把未启动的第三方服务报告为在线。

## 边界

实际 API Key、网关密钥、节点会话、运行数据库、私有 workspace 和用户文件不随本仓库发布。凭据文件采用本机私有文件权限，尚未集成系统钥匙串或静态加密。

产品安装校验清单、摘要、权限和锁定依赖；不会执行市场包中的任意 Python/JS 脚本。远端市场签名、生产多租户、多机调度与 DeepSeek Harness 适配仍待后续实现。


默认地图加载 GeoLibre 3.3.0 的官方资源，并使用 `src/geo_harness/ui/geo-viewer` 中带 MIT 许可与哈希清单的轻量适配器，默认选择 `maplibre-gl-raster`，修复投影 GeoTIFF 首次预览空白。平台与客户端由 Platform 的 `tools/build-geolibre-viewer.py` 同时生成适配文件；升级 GeoLibre 前需重新审核。已安装的官方包、MCP 与 Widget 接口保持原样。

## 与 RuoYi 控制面的验证

本版与 Platform 的官方RuoYi/PostgreSQL统一身份、GeoNode控制面联调。Platform是节点登记、启停和授权的唯一管理入口；客户端从平台公共目录读取已发布能力，运行前由SDK重新核验节点状态与授权。独立客户端和嵌入式工作台使用同一运行时。默认入口为Platform `http://127.0.0.1:3301/`、GeoHarness `http://127.0.0.1:8810/`；19315/18816仅是旧隔离审核端口。

本地节点联调20项及重启后10项通过，包含目录/授权保留、执行审计幂等、共享工作台进入与退出撤销。完整生产多租户、负载与灾备验收尚未完成。更新客户端版本不升级GeoCard、产品manifest或插件自身的独立版本。

## 历史：2026-10-15 main 维护

0.2.2 维护阶段已清理旧版 Vue 客户端及其 Cesium/MapLibre/Vite 依赖链，统一保留 Python 服务与静态界面。该阶段版本为0.2.2，已发布的 v0.2.2 标签位置保持不变；历史维护应使用当时 main 的具体提交与 wheel 哈希。测试清单现在直接覆盖当前地图协议和对话渲染，CI 检查依赖高危告警并构建 Python wheel。生成物、依赖、数据库、密钥和私有 workspace 由统一忽略规则排除。

## RuoYi 地图会话兼容修复

网关与客户端账号关联接受 `ruoyi:12` 等带命名空间的稳定账号ID，保留原始标识，以同一标识的哈希定位已有工作空间。签名、时间窗口、Platform来源、权限、CSRF及产物归属校验继续生效。客户端默认端口8810，默认Platform节点3301，均可通过部署参数明确配置。迁移端口后浏览器需在新入口重新登录，已配置模型和案例仍保存在原私有工作空间。

2026-10-17 本版验证：界面/桌面边界 15 项通过；Python 全量运行中 176 项通过，3 项异步测试因测试环境缺少插件未执行，补齐已有本地 pytest-asyncio 后全部 8 项 host 测试通过；新增市场自动会话回归连同 27 项资源测试通过。GeoLibre 实际 WASI 上传/执行/下载、64 像元校验和跨账号拒绝已验证；OGE 实景可在 GeoLibre 地图加载。
