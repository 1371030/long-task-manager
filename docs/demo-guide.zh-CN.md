# v0.4 Demo 指南

[English](demo-guide.md) | 简体中文

本指南运行 Long Task Manager v0.4 的端到端手动 API demo。脚本不使用 sleep，也不需要外部模型或执行器。

## 启动后端

后端需要 Python 3.11+。从项目根目录执行：

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pytest -q
uvicorn app.main:app --reload --port 8000
```

如果 Python 3.11+ 环境已经激活，可省略创建和激活环境的步骤。

验证：

```http
GET /health
```

```json
{
  "status": "ok",
  "version": "0.4.0"
}
```

## 运行 demo

在另一个终端中，从项目根目录运行：

```bash
API_BASE_URL=http://127.0.0.1:8000 ./scripts/demo_flow.sh
```

脚本需要 `curl` 和 `jq`。请求或断言失败时会以非零状态退出。

## Golden path

Demo 将：

1. 检查 `/health` 的版本为 `0.4.0`。
2. 创建任务和独立 WBS 根节点。
3. 通过子节点 draft proposal 及其审批创建三个原子 WBS 节点：两节点主链和单节点供给链。
4. 通过 draft proposal 及其审批创建两条同根依赖。
5. 使用 Decimal 小时创建确定性、不可变的人工估时修订，并验证规范化类别、修订号、来源和整数毫秒持久化。
6. 生成并批准正常执行计划，接受一次人工 run，并完成既有进度复盘流程。
7. 两次读取 `GET /tasks/{task_id}/wbs/estimate-buffer`，断言输出稳定、时长加权主链和供给链正确、项目/供给缓冲非负，并验证来源与 WBS 版本。
8. 在估时 GET 前后读取 WBS、任务详情和时间线，证明 GET 不修改执行状态或结构，也不创建事件。
9. 输出紧凑 JSON 摘要。

固定人工样本使 PERT 期望值和 RSS 缓冲保持确定。历史 p20/median/p80 行为以及至少三条 accepted run 的阈值由后端回归测试覆盖；demo 有意使用人工优先级，以便快速运行且不伪造基于时间戳的历史。

## Demo 验证的语义

- 估时类别必须显式提供并规范化；系统不会根据标题推断相似性。
- 只有 final accepted approved run 可以进入历史或实际时长依据。
- 人工三点估时修订不可变，并优先于历史数据，直到后续修订清除人工值。
- Decimal 输入小时会持久化并返回为整数毫秒。
- PERT 生成期望时长；历史依据达到至少三条后使用 nearest-rank p20/median/p80。
- 层级感知的 approved-mainline 实际时长会对 Task 和 Step 去重。
- `schedule.node_ids` 是时长加权主链；现有 `critical_path` 仍是基于节点数量的未完成链提示。
- 项目缓冲和供给缓冲使用 RSS 安全量聚合。不可用数据与有效零缓冲使用不同原因/状态；消耗值不会为负。
- 估时 GET 为只读操作。

## 明确排除项

v0.4 不加入截止时间、资源日历、资源调度、自动重排、LLM 关键路径推理或跨根依赖。Demo 也不会执行任意 capability、CLI、Git/GitHub、部署或源码修改操作。
