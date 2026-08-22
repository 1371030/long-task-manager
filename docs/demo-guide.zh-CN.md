# MVP Demo Guide

[English](demo-guide.md) | 简体中文

本指南运行 Long Task Manager 的 Phase 1C 端到端 demo。

该脚本验证手动 API golden path：

1. 创建任务。
2. 添加后续任务消息。
3. 生成包含步骤的计划。
4. 批准计划。
5. 启动一个 `StepRun`。
6. 提交运行结果。
7. 批准已提交的运行。
8. 读取进度、当前指针、结构化下一步动作、时间线事件和产物。

动态步骤、并行变体和能力调用记录由后端回归测试和最小前端 UI 覆盖。

## 启动后端

后端需要 Python 3.11+。不要使用 Python 3.9 虚拟环境。

在项目根目录执行：

```bash
cd backend
rm -rf .venv
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pytest -q
uvicorn app.main:app --reload --port 8000
```

或者，如果 Python 3.11 虚拟环境已经处于激活状态：

```bash
cd backend
python -m pytest -q
uvicorn app.main:app --reload --port 8000
```

后端提供：

```http
GET /health
```

预期响应：

```json
{
  "status": "ok",
  "version": "0.1.1"
}
```

## 启动前端

在另一个终端中：

```bash
cd frontend
npm run dev
```

前端从 `NEXT_PUBLIC_API_BASE_URL` 读取后端 URL，默认值为：

```text
http://127.0.0.1:8000
```

示例：

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

## 运行 API demo 脚本

该 demo 脚本使用 `API_BASE_URL`，默认值为：

```text
http://127.0.0.1:8000
```

在项目根目录运行：

```bash
API_BASE_URL=http://127.0.0.1:8000 ./scripts/demo_flow.sh
```

脚本需要 `jq`。它会在运行工作流前检查 `/health`，任何步骤失败或断言失败都会以非零状态退出。

## Demo 证明的内容

该 demo 证明 MVP 可以通过后端 API 完成完整的受管理工作流：

- 任务接收
- 对话式任务更新
- 计划生成
- 计划批准
- 步骤列表
- 创建步骤运行
- 提交运行结果
- 批准运行
- 进度计算
- 结构化 `current_pointer`
- 带目标 id 的结构化 `next_actions`
- 获取时间线
- 获取产物，包括有效的空列表状态

完整版本还包括动态步骤操作、并行步骤变体和仅记录型能力调用 API。这些功能由后端测试套件验证，并在最小前端中展示。

当前项目还支持可选的 OpenAI-compatible 文本步骤执行和由 tmux 管理的 Codex 执行，但这些能力不在本脚本范围内。

## 当前排除项

本脚本有意不包括：

- 实际能力执行
- 直接 CLI 执行
- Git 或 GitHub 操作
- Source Workspace
- 自动修改源代码
- Temporal
- 部署
- 复杂仪表盘
- 身份认证或授权系统
