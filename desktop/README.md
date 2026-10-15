# GeoHarness 桌面预览

桌面窗口加载本机 `http://127.0.0.1:8810/` 的同一套界面和运行时，直接使用 Platform 用户名/邮箱与密码登录。Platform 仍是唯一账号和权限服务，工作空间继续按完整账号 ID 隔离，模型、对话、任务与案例无需复制。模型密钥不进入 Electron 包。

本阶段交付是轻量桌面壳：需要先启动统一服务；没有打包 Java、PostgreSQL、Redis、Python/GIS 环境，不是离线一体安装包。关闭窗口不会停止统一服务。客户端的退出按钮清除本机登录，不注销 Platform 浏览器会话。

同一本机运行时一次关联一个客户端账号；网页客户端和桌面窗口会跟随此关联，切换账号前需退出。Platform 中的嵌入式工作台仍按各自已验证的网页登录会话隔离。

## 开发与打包

Node 24 环境，在本目录执行 `npm install`，随后 `npm test`、`npm start`。Electron 固定为官方稳定版 44.7.2；只从 npm 官方源和 Electron 官方发布获取依赖。安装后应保留 npm 生成的锁文件，执行依赖审计。

离线 macOS 打包可使用 `python3 package_macos.py --archive /path/electron-v44.7.2-darwin-x64.zip --sha256 <官方SHASUMS256.txt中的完整值> --output /path/output`。脚本校验官方分发包的摘要、保留框架软链接、仅复制明确列出的桌面源文件；不包含工作空间、令牌和用户数据。Apple Silicon 使用对应 arm64 官方归档。

本地构建包仅用于预览。公开分发前需要 Apple Developer 签名、公证、更新机制以及 Windows 签名安装程序；发布阶段另行处理，不能把本地预览视为已签名的正式发行版。

## 窗口边界

Renderer 启用 sandbox、contextIsolation 和 webSecurity，禁用 Node；没有 preload/IPC 文件或命令桥。主页面仅能导航到明确的本机服务，外部新窗口与原生权限请求默认拒绝。Platform 通过应用菜单在系统浏览器打开；地图、下载、工具和账号权限继续由共享运行时管理。

参考：[Electron 安全说明](https://www.electronjs.org/docs/latest/tutorial/security)、[官方稳定版发布](https://releases.electronjs.org/release?channel=stable)。
