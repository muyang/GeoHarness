# 通用完整案例模板

可直接参考 demo-products/synthetic-wetland 的五张 GeoCard、recipe.json、manifest.json、Agent Skill、合成数据与固定模型资产。

| 层 | 文件/对象 | 应声明什么 | 不放什么 |
|---|---|---|---|
| 研究叙述 | Case Card / Markdown | 问题、假设、范围、输入、方法、交付、局限与验收 | 密钥、实时容量 |
| 静态语义 | data / skill / model / compute / workflow GeoCard | 身份、来源、许可、修订、空间与 IO、资源要求 | 健康探测、审核权限 |
| 服务绑定 | ServiceBinding | 协议、部署、工具、所有者、credential_ref | 凭据明文 |
| 动态观测 | ServiceState | available/unavailable/unverified、observed_at、expires_at | 科学有效性承诺 |
| 执行方法 | Recipe | 依赖、参数范围与固定项、输入引用、结果槽位 | 自由文本代替执行契约 |
| 可安装产品 | Manifest | 版本、文件摘要、依赖与权限、Agent Skill | 任意安装脚本 |
| 运行证据 | Run + Lock | 参数、产品/输入/模型/结果摘要、状态、报告 | 虚构结果 |

## 填写顺序

1. 写问题与可检验交付，明确数据是合成、公开还是受限；定义哪些原始数据不得离开节点。
2. 登记真实数据、算子、模型与算力，核验提供者、许可、修订和 IO。缺失项保持未确认。
3. 写有向配方，使用明确的输出引用连接步骤；参数声明类型、范围、默认与可复用/固定范围。
4. 写案例 workflow GeoCard，composition 引用四类卡片，recipe_ref 引用配方。
5. 编制产品 manifest，对每个文件做摘要；明确访问与执行权限，以及固定依赖版本。
6. 安装后先 plan，再执行；保存 lock、派生产物、报告，检验结果是否满足交付与科学假设。

## 本例验收

- threshold=0.6：96 个合成点，35 个正类、61 个负类。
- 相同参数与固定产品版本：分类 GeoJSON SHA-256 相同。
- threshold=0.9：正类数量减少。
- 输出至少包括 classification.geojson、summary.json、plan.json、lock.json、report.md。
- MapLibre/Cesium 项目由真实 GeoLibre MCP authoring 生成，包含 96 个内联点。
- 只有公开合成项目可通过共享 Viewer 路径访问。没有据此推断真实迁徙路线或保护优先级。

迁移至鸟类迁徙案例时，替换数据卡与模型/算子契约，明确观测采样偏差、敏感物种位置授权、时空覆盖、分析假设及验证资料；不得把本示例分类模型当作生态模型。
