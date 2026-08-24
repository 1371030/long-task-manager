# Long Task Manager

English | [简体中文](README.zh-CN.md)

Long Task Manager is a task orchestration and review system for long-running, multi-step work. It organizes tasks, plans, execution attempts, approvals, alternative branches, artifacts, and timelines while allowing humans, OpenAI-compatible models, or an optional tmux-managed Codex executor to participate in step execution.

It is not a general-purpose arbitrary command execution platform, and it does not model shells, browsers, databases, or GitHub operations as core task types.

## Core Model

```text
Task → Step → StepRun → CapabilityInvocation → Approval → Artifact → Event
```

- **Task**: a long-running goal and its constraints
- **Step**: a unit of work and its dependencies
- **StepRun**: one execution attempt for a step; previous attempts are preserved
- **CapabilityInvocation**: a record of a capability call
- **Approval**: a review decision for a plan or run result
- **Artifact**: a file, report, or link produced during execution
- **Event**: a state change or operation in the task timeline

## Features

- Conversational task context and constraint collection
- Manual plans or automatic plan generation through an OpenAI-compatible API
- Plan review and approval
- Dependency-aware step graphs and structured `next_actions`
- Dynamic step appending, insertion, skipping, and superseding
- Step retries, reruns, and preserved run history
- Parallel variants with subtree cloning, comparison, and selection
- Human review, revision requests, and re-execution
- Automatic execution from a task or a selected step
- Progress, timeline, artifact, and CapabilityInvocation queries
- Optional tmux-managed Codex CLI execution

## Execution Modes

### Manual Mode

No API key is required. You can create tasks, define and approve plans manually, submit step results with a human executor type, and inspect progress, reviews, timelines, and artifacts.

### OpenAI-Compatible Mode

After configuring an OpenAI-compatible API, the system can:

- generate task plans automatically;
- produce text results for workflow steps;
- automatically advance through steps whose dependencies are satisfied.

The model executor returns textual workflow results only. It does not run shell commands, modify source code, create pull requests, or deploy applications.

### tmux + Codex Mode

When Codex mode is enabled, a task can reference a local project directory and execute steps with the Codex CLI executor running in tmux. tmux manages the persistent session, while Codex CLI performs the execution. Codex may modify files or run commands according to its sandbox and approval policy, so enable it only for trusted project directories.

## Technology Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy, SQLite
- **Frontend**: Node.js 20.9+, Next.js 16, React 19, TypeScript
- **Optional executors**: OpenAI-compatible API and tmux-managed Codex CLI executor

The backend currently uses local SQLite. It creates `backend/long_task_manager.db` automatically.

## Quick Start

### 1. Start the Backend

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

On Windows PowerShell, activate the virtual environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Once the backend is running, open:

- Health check: <http://127.0.0.1:8000/health>
- OpenAPI documentation: <http://127.0.0.1:8000/docs>

### 2. Start the Frontend

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:3000>.

By default, the frontend connects to `http://127.0.0.1:8000`. The basic manual workflow requires no environment variables.

## Environment Variables

### Backend

Copy the optional configuration template:

```bash
cp backend/.env.example backend/.env
```

See [`backend/.env.example`](backend/.env.example). Every option is commented out by default, so manual mode remains available without configuration.

To enable OpenAI-compatible plan generation and textual step execution, configure at least:

```dotenv
API_KEY=replace-with-provider-key
API_URL=https://provider.example/v1
API_MODEL=replace-with-model-name
PLANNER_PLAN_SYSTEM_PROMPT=Create a concise ordered plan for the task.
```

`PLANNER_PLAN_SYSTEM_PROMPT` seeds the planner prompt only when no prompt is already stored in the database. You can update it later through the UI or `/settings/planner-prompt`.

To customize browser origins, set the process environment variable before starting the backend:

```bash
export CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cp frontend/.env.example frontend/.env.local
```

See [`frontend/.env.example`](frontend/.env.example):

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Values prefixed with `NEXT_PUBLIC_` are included in browser assets and must not contain secrets.

### tmux + Codex

In addition to installing and authenticating the Codex CLI and installing `tmux`, configure at least:

```dotenv
CODEX_ENABLED=true
CODEX_CALLBACK_BASE_URL=http://127.0.0.1:8000
CODEX_CALLBACK_SECRET=replace-with-a-long-random-secret
```

A Codex task also requires a valid `project_path`. The callback URL must be reachable from the Codex process. The command, working directory, tmux session prefix, timeout, retry behavior, sandbox, and approval policy can be adjusted in [`backend/.env.example`](backend/.env.example).

> **Security notice:** The service currently has no authentication or authorization. Do not expose it directly to an untrusted network. The default Codex sandbox and approval policy are permissive; review them and the target project directory before enabling Codex.

## Typical Workflow

1. Create a task and add conversational context.
2. Define a plan manually or ask a model to generate one.
3. Review and approve the plan.
4. Start individual steps or auto-run from the task or a selected step.
5. Review results and approve, request revision, retry, or rerun.
6. Insert, skip, supersede, or fork steps as the workflow changes.
7. Inspect progress, next actions, the timeline, and artifacts.

## Testing

Run backend tests:

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
```

Validate the frontend production build:

```bash
cd frontend
npm run build
```

## API Demo

Start the backend, then run this command from the project root:

```bash
API_BASE_URL=http://127.0.0.1:8000 ./scripts/demo_flow.sh
```

The script requires `curl` and `jq` and validates the manual API workflow. See [`docs/demo-guide.md`](docs/demo-guide.md) for details.

## Project Structure

```text
backend/              FastAPI backend, SQLite data model, and tests
frontend/             Next.js user interface
docs/                 Product, domain model, and API design documents
scripts/demo_flow.sh  Repeatable API demo
```

Additional design documents:

- [Product brief](docs/product-brief.md)
- [System scope](docs/system-scope.md)
- [Domain model](docs/domain-model.md)
- [API design](docs/api-design.md)
- [Iterative StepRun design](docs/iterative-step-runs-design.md)
- [CapabilityInvocation design](docs/capability-invocation-design.md)
- [Historical MVP roadmap](docs/mvp-roadmap.md)
- [Future roadmap](docs/future-roadmap.md)

## License

This project is licensed under the [MIT License](LICENSE).
