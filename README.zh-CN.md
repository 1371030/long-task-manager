# Long Task Manager

[English](README.md) | 简体中文

Long Task Manager 是一个面向长时间、多步骤工作的任务编排与审核系统。它负责组织任务、计划、执行尝试、审批、分支方案、产物和时间线，并允许人工、OpenAI-compatible 模型或可选的 Codex CLI 参与步骤执行。

它不是通用的任意命令执行平台，也不把 shell、浏览器、数据库或 GitHub 操作直接建模为任务核心类型。

## 核心模型

```text
Task → Step → StepRun → CapabilityInvocation → Approval → Artifact → Event
```

- **Task**：需要长期推进的目标及其约束
- **Step**：计划中的工作步骤及依赖关系
- **StepRun**：某个步骤的一次执行尝试，历史尝试不会被覆盖
- **CapabilityInvocation**：一次能力调用记录
- **Approval**：对计划或运行结果的审核结论
- **Artifact**：执行过程中产生的文件、报告或链接
- **Event**：任务时间线中的状态变化与操作记录

## 当前能力

- 对话式补充任务目标、上下文和约束
- 手动创建计划，或通过 OpenAI-compatible API 自动生成计划
- 计划审核和批准
- 依赖感知的步骤图与结构化 `next_actions`
- 动态追加、插入、跳过和替代步骤
- 步骤重试、重跑及历史运行记录
- fork 并行方案、复制子步骤、比较和选择 variant
- 人工审核、打回修改和重新执行
- 从任务或指定步骤开始自动运行后续可执行步骤
- 进度、时间线、产物和 CapabilityInvocation 查询
- 可选的 Codex CLI + tmux 执行模式

## 使用模式

### 手动模式

无需 API Key。可以创建任务、手动制定并批准计划、使用人工执行类型提交步骤结果，以及查看进度、审核、时间线和产物。

### OpenAI-compatible 模式

配置 OpenAI-compatible API 后，可以：

- 自动生成任务计划
- 生成文本形式的步骤结果
- 自动运行依赖已满足的步骤

模型执行器只返回工作流步骤的文本结果，不会自行运行 shell、修改源码、创建 PR 或部署。

### Codex + tmux 模式

启用 Codex 后，任务可以关联一个本地项目目录，并通过持久化 tmux session 调用 Codex CLI 执行步骤。Codex 可能根据其 sandbox 和 approval policy 修改文件或执行命令，因此只应对可信项目目录启用。

## 技术栈

- **Backend**：Python 3.11+、FastAPI、SQLAlchemy、SQLite
- **Frontend**：Node.js 20.9+、Next.js 16、React 19、TypeScript
- **可选执行器**：OpenAI-compatible API、Codex CLI、tmux

当前后端使用本地 SQLite，数据库文件会在 `backend/long_task_manager.db` 自动创建。

## 快速开始

### 1. 启动后端

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Windows PowerShell 激活虚拟环境：

```powershell
.venv\Scripts\Activate.ps1
```

后端启动后可访问：

- 健康检查：<http://127.0.0.1:8000/health>
- OpenAPI 文档：<http://127.0.0.1:8000/docs>

### 2. 启动前端

在另一个终端执行：

```bash
cd frontend
npm ci
npm run dev
```

打开 <http://localhost:3000>。

默认情况下，前端请求 `http://127.0.0.1:8000`，基础手动流程不需要配置任何环境变量。

## 环境变量

### Backend

复制可选配置模板：

```bash
cp backend/.env.example backend/.env
```

模板见 [`backend/.env.example`](backend/.env.example)。所有选项默认均被注释，不配置时仍可使用手动模式。

启用 OpenAI-compatible 计划生成和文本步骤执行时，至少配置：

```dotenv
API_KEY=replace-with-provider-key
API_URL=https://provider.example/v1
API_MODEL=replace-with-model-name
PLANNER_PLAN_SYSTEM_PROMPT=Create a concise ordered plan for the task.
```

`PLANNER_PLAN_SYSTEM_PROMPT` 只会在数据库尚未保存 planner prompt 时用于初始化；之后可以通过 UI 或 `/settings/planner-prompt` 修改。

如需自定义浏览器来源，应在启动后端前设置进程环境变量：

```bash
export CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cp frontend/.env.example frontend/.env.local
```

模板见 [`frontend/.env.example`](frontend/.env.example)：

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

`NEXT_PUBLIC_*` 会进入浏览器端资源，不能用于保存密钥。

### Codex + tmux

除安装并登录 Codex CLI、安装 `tmux` 外，至少需要：

```dotenv
CODEX_ENABLED=true
CODEX_CALLBACK_BASE_URL=http://127.0.0.1:8000
CODEX_CALLBACK_SECRET=replace-with-a-long-random-secret
```

创建 Codex 模式任务时还需要提供有效的 `project_path`。回调地址必须能被 Codex 进程访问。命令、工作目录、tmux session 前缀、超时、重试、sandbox 和 approval policy 均可通过 [`backend/.env.example`](backend/.env.example) 调整。

> **安全提示**：当前服务没有身份认证或授权机制，请勿直接暴露到不可信网络。应用默认的 Codex sandbox 与 approval policy 较宽松，启用前务必检查配置和目标项目目录。

## 典型流程

1. 创建任务并通过消息补充上下文。
2. 手动创建计划，或请求模型生成计划。
3. 审核并批准计划。
4. 单独启动步骤，或从任务/指定步骤开始 auto-run。
5. 审核结果，选择批准、打回、重试或重跑。
6. 根据任务变化插入、跳过、替代或 fork 步骤。
7. 查看进度、下一步动作、时间线和产物。

## 测试

运行后端测试：

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
```

验证前端生产构建：

```bash
cd frontend
npm run build
```

## API Demo

先启动后端，再从项目根目录运行：

```bash
API_BASE_URL=http://127.0.0.1:8000 ./scripts/demo_flow.sh
```

脚本需要 `curl` 和 `jq`，并验证手动 API 流程。详细说明见 [`docs/demo-guide.zh-CN.md`](docs/demo-guide.zh-CN.md)。

## 项目结构

```text
backend/              FastAPI 后端、SQLite 数据模型与测试
frontend/             Next.js 用户界面
docs/                 产品、领域模型与 API 设计文档
scripts/demo_flow.sh  可重复运行的 API demo
```

更多设计资料：

- [产品说明](docs/product-brief.zh-CN.md)
- [系统范围](docs/system-scope.zh-CN.md)
- [领域模型](docs/domain-model.zh-CN.md)
- [API 设计](docs/api-design.zh-CN.md)
- [StepRun 迭代设计](docs/iterative-step-runs-design.zh-CN.md)
- [CapabilityInvocation 设计](docs/capability-invocation-design.zh-CN.md)
- [历史 MVP 路线](docs/mvp-roadmap.zh-CN.md)

## License

本项目采用 [MIT License](LICENSE)。
