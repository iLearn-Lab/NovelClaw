# NovelClaw

<div align="center">
  <p>
    <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
    <img src="https://img.shields.io/badge/FastAPI-Writing%20Workspace-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI writing workspace">
    <img src="https://img.shields.io/badge/Scope-Long--Form%20Fiction-F97316?style=for-the-badge" alt="Long-form fiction">
    <img src="https://img.shields.io/badge/Mode-Chapter%20Control%20%26%20Memory-0f766e?style=for-the-badge" alt="Chapter control and memory">
    <img src="https://img.shields.io/badge/Release-GitHub%20Safe-f59e0b?style=for-the-badge" alt="GitHub-safe release">
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-111827?style=for-the-badge" alt="MIT License"></a>
  </p>

  <h3>✨ 一个围绕章节写作、运行可观测性、稿件审阅与记忆感知控制而构建的结构化长篇小说工作台。</h3>

  <p>
    💡 NovelClaw 不是一次性提示词封装，而是把长篇创作整理成一个可检查的写作工作区：包含 sessions、storyboard、manuscript 视图、角色与世界观界面，以及可编辑的 memory bank。
  </p>

  <p>
    <b>🌐 在线体验入口：</b><a href="https://colong-idea-studio.cloud/">colong-idea-studio.cloud</a>
  </p>

  <p>
    <b>🚀 立即本地启动：</b> <code>.\START_LOCAL.bat</code>
  </p>

  <p>
    <a href="https://colong-idea-studio.cloud/"><img src="https://img.shields.io/badge/在线平台-立即体验-0f766e?style=flat-square&logo=googlechrome&logoColor=white" alt="在线平台"></a>
    <a href="README.md"><img src="https://img.shields.io/badge/English-README-ef4444?style=flat-square" alt="English README"></a>
    <a href="RUN_LOCAL_WEB.md"><img src="https://img.shields.io/badge/本地运行-启动说明-f59e0b?style=flat-square&logo=readthedocs&logoColor=white" alt="本地运行指南"></a>
    <a href="DEPLOYMENT.md"><img src="https://img.shields.io/badge/部署-服务器说明-0f766e?style=flat-square" alt="部署文档"></a>
    <a href="WHAT_IS_SAFE_FOR_GITHUB.md"><img src="https://img.shields.io/badge/GitHub%20Safe-公开检查表-111827?style=flat-square" alt="GitHub 安全说明"></a>
  </p>

  <p>
    <a href="#概览">概览</a> |
    <a href="#视觉预览">视觉预览</a> |
    <a href="#为什么它更特别">为什么它更特别</a> |
    <a href="#工作流">工作流</a> |
    <a href="#快速开始">快速开始</a> |
    <a href="#claw-mode-guide">Claw 模式操作</a> |
    <a href="#架构">架构</a> |
    <a href="#运行产物">运行产物</a>
  </p>
</div>

<p align="center">
  <video src="docs/novelclaw-demo.mp4" controls muted playsinline preload="metadata" poster="docs/hero.png" width="100%">
    当前环境不支持内嵌视频。<a href="docs/novelclaw-demo.mp4">点此下载 NovelClaw 演示视频</a>。
  </video>
</p>

<p align="center">
  <sub>NovelClaw 工作区演示视频预览。</sub>
</p>

> 🚀 **本地预览**
> 👀 从 **`http://127.0.0.1:8010/select-mode`** 进入后，可继续前往 **`http://127.0.0.1:8012/dashboard`**，这才是主要的 NovelClaw 工作区。

> 🌐 **在线体验**
> 直接访问 **[colong-idea-studio.cloud](https://colong-idea-studio.cloud/)**，这是最快体验线上平台的方式。

## 概览 🌟

`NovelClaw` 是这个 GitHub 安全公开版中的核心写作工作区。虽然仓库中仍然包含 `Portal` 与 `MultiAgent`，但前者主要负责公开入口，后者主要负责可选的快速构思通道；真正持续性的长篇写作体验集中在 NovelClaw 本身。

与把长篇创作视为一次性 prompt 提交不同，NovelClaw 把工作组织为持续会话、运行检查、稿件审阅、故事板推进，以及围绕记忆的写作控制过程。

这使它更适合那些希望获得更强连续性、更清晰迭代界面，以及更直接章节级控制能力的作者与构建者。🎯

- 📚 长篇小说、连载式写作与分章续写
- 🧠 带有可检查章节产物和可复用故事状态的记忆感知写作
- 🤝 人机协同、作者持续介入的写作工作流
- 🔍 包含日志、进度轨迹、章节产出、下载与审阅界面的可观测运行过程

<table>
  <tr>
    <td width="33%" valign="top">
      <h3>✍️ 写作工作区</h3>
      <p>NovelClaw 把对话、章节写作、运行审阅与续写控制放进同一个主工作区，而不是拆散到多个页面或临时工具中。</p>
    </td>
    <td width="33%" valign="top">
      <h3>🗂️ 稿件工作面</h3>
      <p>storyboard、manuscript、style、world 与 character 界面都作为持续可见的工作材料存在，而不是隐藏的中间产物。</p>
    </td>
    <td width="33%" valign="top">
      <h3>🧠 记忆控制</h3>
      <p>可编辑的 memory bank、与 run 关联的产物，以及章节输出，共同构成连续性维护、修订与复用的具体操作面。</p>
    </td>
  </tr>
</table>

## 视觉预览 👀

<p align="center">
  <img src="docs/readme-triptych-en.png" alt="从干净入口到持续写作，再到可检查的章节控制" width="100%">
</p>

NovelClaw 的核心判断很明确：长篇写作质量的提升，不只取决于模型能否写出文本，更取决于写作、审阅与记忆控制是否被组织成一个持续性的工作空间。✨

## 为什么它更特别 ✨

<p align="center">
  <img src="docs/dynamic-memory.png" alt="NovelClaw 在章节、记忆与可检查产物之间形成的工作流" width="100%">
</p>

| 常见小说工具流程 | NovelClaw |
|---|---|
| 把长篇写作当成一次性的大 prompt | 把长篇写作组织成包含 sessions 与 run inspection 的持续工作区 |
| 把执行状态藏在不透明的生成流程后面 | 直接暴露 worker 输出、`progress.log`、章节文件、下载和 job 详情界面 |
| 故事状态散落在临时 prompt 里 | 把 manuscript、world、character 与 memory bank 保留在工作区内部 |
| 首次生成之后很难继续控制 | 支持通过 sessions、storyboard、manuscript review 与 chapter monitoring 持续回到项目中 |
| 公开版容易混入本地残留 | 配套 GitHub-safe 打包策略、安全 env 模板与部署参考 |

### NovelClaw 的实际工作方式 🧠

- 📝 conversation sessions 会持续保留为当前写作语境的一部分
- 📌 章节产出、进度轨迹与下载产物在运行期间始终可检查
- 👤 world、character、style 与 manuscript 界面会持续参与修订与续写过程
- 🔁 Portal 与 MultiAgent 可以辅助入口和前置准备，但主要的长篇控制界面仍然是 NovelClaw

## 工作流 🔄

<table>
  <tr>
    <td width="25%" valign="top">
      <h4>1. 进入</h4>
      <p>从 <code>/select-mode</code> 这个公开入口开始，使公开版与旧的私有认证流程保持清晰分离。</p>
    </td>
    <td width="25%" valign="top">
      <h4>2. 准备</h4>
      <p>如有需要，可先借助辅助层完成 provider 配置或更快的创意细化，再进入主写作工作区。</p>
    </td>
    <td width="25%" valign="top">
      <h4>3. 写作</h4>
      <p>在 NovelClaw 中继续 sessions、监控 runs、检查 chapters，并直接推进 manuscript 的发展。</p>
    </td>
    <td width="25%" valign="top">
      <h4>4. 审阅</h4>
      <p>通过 manuscript、storyboard、world、character、style 与 memory bank 等界面，维持项目在增长过程中的一致性。</p>
    </td>
  </tr>
</table>

## 适合的场景 🎯

- 📖 分章推进的长篇小说与连载写作工作流
- 🧠 需要连续性跟踪，而不是一次性产出的写作项目
- 🤝 作者持续介入、需要监督和修订的协同写作过程
- 🧪 面向可观测长篇写作系统的工程实验与产品探索

## 快速开始 🚀

<details open>
<summary><b>🐳 方案 A：Docker 部署（推荐）</b></summary>

💻 使用 Docker 快速启动：

**Windows 用户：**
```batch
.\docker-start.bat
```

**Linux/Mac 用户：**
```bash
chmod +x docker-start.sh
./docker-start.sh
```

**或手动启动：**
```bash
# 1. 配置环境变量文件
cp .env.auth-portal.example apps/auth-portal/.env
cp .env.multiagent.example apps/multiagent/.env
cp .env.novelclaw.example apps/novelclaw/.env

# 2. 编辑 .env 文件，添加你的 API 密钥

# 3. 启动服务
docker-compose up -d
```

🌐 访问地址：

```text
Portal      http://localhost:8010/select-mode
MultiAgent  http://localhost:8011/dashboard
NovelClaw   http://localhost:8012/dashboard
```

✅ Docker 部署优势：

- 无需配置 Python 环境
- 跨平台部署一致性
- 易于启动、停止和管理服务
- 通过卷挂载实现数据持久化

📖 详细的 Docker 部署指南请参考 [DOCKER_DEPLOYMENT.zh-CN.md](DOCKER_DEPLOYMENT.zh-CN.md)

</details>

<details>
<summary><b>🌐 方案 B：一键启动本地整套栈</b></summary>

💻 Windows 下推荐：

```powershell
.\START_LOCAL.bat
```

🌐 本地地址：

```text
Portal      http://127.0.0.1:8010/select-mode
MultiAgent  http://127.0.0.1:8011/dashboard
NovelClaw   http://127.0.0.1:8012/dashboard
```

✅ 推荐主路径：

```text
http://127.0.0.1:8010/select-mode -> http://127.0.0.1:8012/dashboard
```

✅ 这个脚本会做什么：

- 停掉 `8010`、`8011` 和 `8012` 上旧的监听进程
- 用安全默认值写入本地 `.env` 文件
- 准备共享 `.venv-shared`
- 启动 `Portal`、`MultiAgent` 和 `NovelClaw`

</details>

<details>
<summary><b>⌨️ 方案 B：手动 PowerShell 启动</b></summary>

```powershell
.\scripts\setup-local-env.ps1 -Overwrite
.\scripts\bootstrap-shared-venv.ps1
.\scripts\start-all-local.ps1 -UseSharedVenv
```

🛑 停止全部服务：

```powershell
.\STOP_LOCAL.bat
```

🛠️ 常用命令：

```powershell
.\scripts\stop-all-local.ps1
.\scripts\start-all-local.ps1 -UseSharedVenv -RestartExisting
```

</details>

<a id="claw-mode-guide"></a>
## Claw 模式操作 🛠️

如果你的目标是进入主 NovelClaw 写作工作区，最实用的操作路径可以概括为以下几个步骤：

1. 进入工作区
   先从 `http://127.0.0.1:8010/select-mode` 进入，选择 `NovelClaw`，再继续前往 `http://127.0.0.1:8012/dashboard`。
1. 先配置模型
   打开 `/console/models`，为可用 provider 保存 API Key；如果不想使用默认 provider，也可以先添加自定义 provider。若没有完成这一步，chat 工作区会提示你先完成配置。
1. 启动写作会话
   打开 `/console/chat`，选择 provider，提交初始故事前提、风格、角色设定或写作任务。NovelClaw 会建立一条持续会话线程，在需要时继续追问细化，并在准备完成后把当前 brief 交给正式创作流程。
1. 跟踪运行过程
   打开 `/console/tasks` 或对应的 job 详情页，检查 run 状态、`worker.log`、`progress.log`、章节产出以及可下载产物，持续观察写作过程。
1. 审阅并继续推进
   使用 `/console/manuscript/read` 阅读章节，使用 `/console/storyboard` 查看大纲与情节结构，使用 `/console/memory/banks` 检查或编辑记忆内容。之后再回到 `/console/chat`，在原会话上继续推进，而不是每次从头开始。

简而言之：`Models` 用来配置写作栈，`Chat` 用来启动并推进会话，`Runs` 用来观察执行状态，而 `Manuscript / Storyboard / Memory Banks` 则构成正式生成之后最重要的续写与审阅工作面。

## 你会得到什么 🎁

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>🎨 工作区能力</h3>
      <ul>
        <li>持续写作 sessions</li>
        <li>manuscript 与 storyboard 视图</li>
        <li>world、character 与 style 工作面</li>
        <li>可编辑的 memory bank 工具</li>
      </ul>
    </td>
    <td width="50%" valign="top">
      <h3>🔍 可检查产物</h3>
      <ul>
        <li>worker logs 与 progress traces</li>
        <li>chapter output 与可下载产物</li>
        <li>job detail 与 run review 界面</li>
        <li>GitHub-safe 部署参考</li>
      </ul>
    </td>
  </tr>
</table>

## 架构 🧠

<p align="center">
  <img src="docs/workflow.png" alt="NovelClaw 工作流图" width="94%">
</p>

整个架构把公开入口、写作会话、运行执行、稿件审阅与记忆感知续写连接成一个可检查的闭环，使工作区在面对更长项目时，不会退化成一次性且不透明的 prompt 交互。

## 运行产物 📦

最值得检查的 NovelClaw 路径通常是：

```text
apps/novelclaw/local_web_portal/data/app.db
apps/novelclaw/local_web_portal/runs/<run_id>/
```

一个 run 目录中最有代表性的文件包括：

```text
status.json
worker.log
progress.log
output.txt
chapters/
```

`progress.log` 中比较关键的事件包括：

| 事件 | 含义 |
|---|---|
| `global_outline` | 全局大纲已落盘 |
| `chapter_outline_ready` | 章节大纲已准备完成 |
| `chapter_plan` | 当前章节写作计划 |
| `chapter_length_plan` | 当前章节目标长度及其来源 |
| `memory_snapshot` | 记忆快照已刷新 |
| `character_setting` / `world_setting` | 设定记忆已回写 |

<details>
<summary><b>仓库结构</b></summary>

```text
.
|-- apps/
|   |-- auth-portal/       # 公开入口层
|   |-- multiagent/        # 可选的快速构思层
|   `-- novelclaw/         # 主写作工作区
|-- scripts/               # 本地初始化 / 启动 / 停止辅助脚本
|-- docs/                  # 截图与运维说明
|-- infra/
|   |-- nginx/             # 反向代理示例
|   |-- systemd/           # 服务单元示例
|   `-- env/               # 仅保留安全环境模板
`-- state_snapshots/       # 为公开安全发布而刻意清空
```

</details>

<details>
<summary><b>部署说明</b></summary>

- 只上传源码、文档和基础设施参考文件
- 真实 `.env` 和密钥必须放在仓库之外
- 跑过本地栈之后，不要提交运行数据库、恢复后的快照或本地密钥
- 把 `/claw/` 视为主产品路由，把 `/select-mode` 视为它的公开入口

更偏运维侧的说明可查看 [docs/DEPLOYMENT.zh-CN.md](docs/DEPLOYMENT.zh-CN.md)、[docs/LOCAL_RUN.zh-CN.md](docs/LOCAL_RUN.zh-CN.md)、[DEPLOYMENT.md](DEPLOYMENT.md)、[RUN_LOCAL_WEB.md](RUN_LOCAL_WEB.md) 和 [WHAT_IS_SAFE_FOR_GITHUB.md](WHAT_IS_SAFE_FOR_GITHUB.md)。

</details>

## 🙇‍ 特别感谢
[Linux.do](https://linux.do/)

## 更多文档 📚

- 🇬🇧 English README: [README.md](README.md)
- 🌐 本地运行指南: [docs/LOCAL_RUN.zh-CN.md](docs/LOCAL_RUN.zh-CN.md)
- 🌐 Local run guide: [RUN_LOCAL_WEB.md](RUN_LOCAL_WEB.md)
- 🛠️ 部署说明: [docs/DEPLOYMENT.zh-CN.md](docs/DEPLOYMENT.zh-CN.md)
- 🛠️ Deployment guide: [DEPLOYMENT.md](DEPLOYMENT.md)
- 🔐 GitHub 安全说明: [WHAT_IS_SAFE_FOR_GITHUB.md](WHAT_IS_SAFE_FOR_GITHUB.md)
- ⚖️ 许可证: [MIT](LICENSE)
