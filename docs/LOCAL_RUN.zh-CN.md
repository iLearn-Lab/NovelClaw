# 本地运行 NovelClaw

这个公开版中的主工作区是 `NovelClaw`。`Portal` 负责公开入口，`MultiAgent` 提供可选的快速构思通道，但本地使用时最推荐的路径是：

```text
http://127.0.0.1:8010/select-mode -> http://127.0.0.1:8012/dashboard
```

## 推荐路径

1. 启动本地整套服务。
2. 打开 `http://127.0.0.1:8010/select-mode`。
3. 选择 `NovelClaw`。
4. 进入 `/console/models`，先为 provider 保存 API Key。
5. 进入 `/console/chat`，启动写作会话。
6. 通过 `/console/tasks` 检查运行过程，并通过 `/console/manuscript/read`、`/console/storyboard`、`/console/memory/banks` 审阅和继续推进项目。

## 一键启动

```powershell
.\START_LOCAL.bat
```

这个脚本会自动：

1. 停掉 `8010`、`8011`、`8012` 上旧的监听进程。
2. 为缺失的配置创建 `.env` 文件，保留已有设置。
3. 准备共享的 `.venv-shared`。
4. 在后台启动 `Portal`、`MultiAgent` 和 `NovelClaw`，并检查服务就绪状态。

服务日志位于各应用的 `local_web_portal/data/logs/` 目录。

## 一键停止

```powershell
.\STOP_LOCAL.bat
```

## 手动启动

```powershell
.\scripts\setup-local-env.ps1
.\scripts\bootstrap-shared-venv.ps1
.\scripts\start-all-local.ps1 -UseSharedVenv
```

如果服务已经在运行，需要强制重启：

```powershell
.\scripts\start-all-local.ps1 -UseSharedVenv -RestartExisting
```

## 本地地址

- `Portal`：`http://127.0.0.1:8010/select-mode`
- `MultiAgent`：`http://127.0.0.1:8011/dashboard`
- `NovelClaw`：`http://127.0.0.1:8012/dashboard`

## Claw 模式下的主要页面

进入主 NovelClaw 工作区后，最常用的页面通常是：

- `/console/models`
  配置 provider、模型和 API Key。
- `/console/chat`
  启动或继续主写作会话。
- `/console/tasks`
  检查当前和历史 runs，并进入 job 详情页。
- `/console/manuscript/read`
  阅读和审阅章节产出。
- `/console/storyboard`
  查看大纲、情节点和章节推进情况。
- `/console/memory/banks`
  检查和编辑与项目关联的 memory bank 内容。

## 说明

- 即使最终目标是 NovelClaw，也建议先从 `8010/select-mode` 进入。
- 这个公开版不会暴露旧的注册、登录、找回密码或邮箱验证流程。
- 本地预览默认不需要 Nginx。
- 本地默认设置了 `EMBEDDING_MODEL=none` 和 `DISABLE_EMBEDDING_DOWNLOADS=1`，避免预览阶段触发较重的 embedding 下载。
