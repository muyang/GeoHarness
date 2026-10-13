# 共享工作台与真实案例

本轮审核预览：Platform http://127.0.0.1:9316/workbench；GeoHarness http://127.0.0.1:8810/。原有9305/8809实例保持运行。本轮代码只在既有v02功能worktree和独立客户端副本中，未提交。

## 使用

1. Platform 使用 member / Demo@GeoNexus2026 登录（邮箱 member@geonexus.local），进入工作台。管理员预览使用 admin / Admin@GeoNexus2026，账号空间分别隔离。
2. 客户端“模型与设置”中的 Platform 登录完成后，从工作台“关联 Platform 账号”进入同一账号空间。默认 Platform 节点仍不可删除或改址。
3. 两张真实案例卡分别为香港局部人口汇总和武汉2020-12-25 Landsat NDVI。勾选卡上的本次授权，再点击运行；状态为完成后才可打开地图与保存案例。数据窗口、输入快照、质量掩膜和计算方式固定，不能外推到全市或当前年份。
4. 工作台“启用常用工具”安装18个审核算子和2个任务控制产品。查看契约、选择工具、上传GeoJSON/GeoTIFF输入（最多1MiB）、勾选本次计算授权后执行。输入上传到卡片声明的节点，用不含路径的私有引用调用。结果引用可以继续作为同节点输入，不能跨节点直接混用。
5. 地图支持实际视野、图层、字段及选择的摘要；可定位成果、显隐图层、撤销操作。最终栅格默认显示，中间栅格可主动开启；共享入口切换时，成果URL重写到当前经过认证的同源入口。
6. 从已完成记录“保存为案例卡”。导出含符合GeoCard schema的workflow卡、无凭据recipe、输入参数/产品摘要/来源/科学限制/产物哈希。固定真实workflow可重跑；任意上传算子的案例标为需要重新提供输入，私有输入有24小时期限，不承诺永久复现。

## AI 助手

用户自行配置OpenAI Chat Completions兼容服务地址、准确模型ID和API Key（也可使用本机兼容服务），启用并测试连接后发起对话。新的研究助手与地图使用同一工作台运行时；Platform和关联客户端共享同账号的模型配置。新账号不会继承本机主空间密钥。本轮真实计算不需要LLM，模型工具协议与地图确认流使用可控测试模型验证，未使用用户的付费模型凭据进行外部调用。

助手采用搜索→按需描述契约→提交→查询状态→地图查看→保存案例的工具流程，最多12轮、每轮8个工具调用。地图确认和远程状态按实际返回报告；未知图层、过期摘要或未安装/未授权产品被拒绝。LLM只收到公开已安装产品和批准的地图摘要，不接收私有节点session、产物access_token或Platform令牌。Map view/GeoCard/skill文字作为不可信数据，不能自动安装产品、授予权限或执行主机命令。

## 接口

共享运行时：`/api/workbench/context`、`project`、`map/sync`、`action`、`map/ack/{id}`；`operators`与`operators/{id}`；`inputs`；`executions`及状态/停止等待；`cases`、`cases/save`、`cases/{id}/export`和`replay`；`chat/stream`为NDJSON逐步事件。停止等待不代表已经取消远程计算，可使用节点的私有任务取消工具查看实际结果。

Platform：`POST /api/workbench/session` 验证Bearer账号和workbench:run权限；`/api/workbench/runtime/*`经HttpOnly会话和逐请求权限校验转发到固定本机GeoHarness。`POST /api/v1/node-artifacts`仅支持显式授权、已发布卡片与被审核的GeoMCP上传绑定，固定节点上传路径、限制大小，校验返回哈希/字节数。成果网关验证任务所有者、文件哈希和私有令牌，不跟随任意重定向。

## 运行与边界

查看器：官方GeoLibre3.3.0同源bundle；执行器：固定GeoLibre WASI1.6.0。二者版本分别管理。官方MCP HTTP与GeoMCP HTTP指向同一执行状态；不将GIS计算或知识图谱写进轻量SDK。

现有工作区的`work/shared-workbench-upgrade/launch_preview.py`启动Platform/接口桥/GeoHarness；GeoNode按`platform-repo/geonodes/geolibre/README.md`单独启动9314及官方MCP9315。启动脚本从私有preview-runtime读取网关Key，它们不随源码/审核包交付；应为新部署生成独立随机Key，不复用旧运行数据库或凭据。节点审核绑定WASM/执行代码/输入契约，修改后须重新审核。数据输入和案例脚本也独立绑定哈希。

当前是单机回环地址审核预览：生产HTTPS网关、企业身份/租户存储、多机调度、发布者签名和更多资源接入需要后续实现。旧的GeoKG客户端integration测试存在基线差异；本轮未修改SDK或GeoKG源码，不宣称全部历史suite通过。QGIS/OGE/未审核算子不在本次新接入范围。
