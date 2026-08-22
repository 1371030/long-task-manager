"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, MouseEvent, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  abandonStepVariant,
  addTaskMessage,
  approvePlan,
  Artifact,
  autoRunFromStep,
  autoRunTask,
  CapabilityInvocation,
  closeTask,
  createCapabilityInvocation,
  createRun,
  createStep,
  forkStep,
  generatePlan,
  getPlannerPrompt,
  getStepComparison,
  getTask,
  listArtifacts,
  listCapabilityInvocations,
  listRuns,
  listTimeline,
  rerunStep,
  retryStep,
  reviewRun,
  selectStepVariant,
  skipStep,
  PlannerPromptConfig,
  Step,
  StepComparisonGroup,
  StepRun,
  submitRun,
  supersedeStep,
  TaskDetail,
  TaskMessage,
  TimelineEvent,
  updateCapabilityInvocation,
  updatePlannerPrompt,
  updateStep,
} from "../../../lib/api";

const defaultPlanSteps = [
  { title: "Clarify scope", objective: "Confirm the task goal, constraints, and expected output." },
  { title: "Execute first pass", objective: "Perform the first concrete work step and prepare it for review." },
];

const stepStatusLabels: Record<string, string> = {
  pending: "Step pending",
  running: "Step running",
  waiting_review: "Step waiting for review",
  needs_revision: "Step needs revision",
  approved: "Step completed",
  failed: "Step failed",
  skipped: "Step skipped",
  superseded: "Step superseded",
};

const runStatusLabels: Record<string, string> = {
  running: "Run in progress",
  submitted: "Submitted for review",
  accepted: "Run approved",
  rejected: "Revision requested",
  failed: "Run failed",
  cancelled: "Run cancelled",
};

function statusLabel(labels: Record<string, string>, status: string) {
  return labels[status] ?? status;
}

function rawDetails(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function formatErrorMessage(message: string) {
  const raw = message.replace(/^Error:\s*/, "").trim();
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail)) return parsed.detail.map((item) => typeof item === "string" ? item : JSON.stringify(item)).join("; ");
  } catch {
    return message;
  }
  return message;
}

function formatDuration(ms: number | null | undefined) {
  if (ms === null || ms === undefined) return "not available";
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  return `${seconds}s`;
}

function runDisplayDuration(run: StepRun, nowMs: number) {
  if (run.status === "running" && run.started_at) {
    return Math.max(0, nowMs - new Date(run.started_at).getTime());
  }
  return run.duration_ms;
}

function stepDisplayDuration(step: Step, runs: StepRun[], nowMs: number) {
  if (runs.length === 0) return step.consumed_ms;
  return runs.reduce((total, run) => total + (runDisplayDuration(run, nowMs) ?? 0), 0);
}

function textValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value : null;
}

function runSummary(run: StepRun) {
  const output = run.output;
  if (run.error) return run.error;
  if (!output) return run.status === "running" ? "Waiting for executor output." : "No output recorded yet.";
  return textValue(output.summary) ?? textValue(output.error) ?? textValue(output.status) ?? "Output recorded.";
}

function capabilitySummary(invocation: CapabilityInvocation) {
  if (invocation.error) return invocation.error;
  if (!invocation.output) return "No output recorded yet.";
  return textValue(invocation.output.summary) ?? textValue(invocation.output.error) ?? "Output recorded.";
}

type RunsByStep = Record<number, StepRun[]>;

type StepGraphEdgeType = "sequence" | "dependency" | "parent" | "fork" | "supersede";

type StepGraphEdge = {
  id: string;
  from: number;
  to: number;
  type: StepGraphEdgeType;
};

type StepGraphNode = {
  step: Step;
  x: number;
  y: number;
  width: number;
  height: number;
  lane: number;
  column: number;
  displayOrder: number;
};

const workflowNodeWidth = 340;
const workflowNodeHeight = 240;
const workflowColumnGap = 96;
const workflowRowGap = 88;
const workflowPadding = 28;

const excludedBranchStatuses = ["not_selected", "abandoned", "superseded"];

function stepAllowsAction(step: Step) {
  return step.is_active && step.status !== "superseded" && !excludedBranchStatuses.includes(step.branch_status ?? "");
}

function canBranchRun(step: Step, hasRunningOrReviewStep: boolean) {
  return stepAllowsAction(step) && !hasRunningOrReviewStep && ["approved", "needs_revision", "failed", "skipped"].includes(step.status);
}

function canRetryInPlace(step: Step, hasRunningOrReviewStep: boolean) {
  return stepAllowsAction(step) && !hasRunningOrReviewStep && ["approved", "needs_revision", "failed"].includes(step.status);
}

function branchRunLabel(step: Step) {
  if (step.status === "needs_revision") return "Revision branch";
  if (step.status === "failed") return "Retry branch";
  if (step.status === "skipped") return "Branch skipped";
  return "Branch run";
}

function retryLabel(step: Step) {
  return step.status === "approved" ? "Rerun" : "Retry";
}

function nextActionStepId(detail: TaskDetail) {
  return detail.next_actions.find((action) => action.action_type === "start_step_run" || action.action_type === "auto_run_from_step")?.target.step_id ?? null;
}

function parseTaskId(value: string | string[] | undefined) {
  const raw = Array.isArray(value) ? value[0] : value;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function initialSelectedStepId(steps: Step[], nextStepId: number | null = null) {
  return steps.find((step) => ["running", "waiting_review", "needs_revision", "failed"].includes(step.status))?.id ?? nextStepId ?? steps[0]?.id ?? null;
}

function uniqueEdges(edges: StepGraphEdge[]) {
  const seen = new Set<string>();
  return edges.filter((edge) => {
    const key = `${edge.from}-${edge.to}-${edge.type}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function buildStepGraph(steps: Step[]) {
  const orderedSteps = [...steps].sort((left, right) => left.step_order - right.step_order || left.position - right.position || left.id - right.id);
  const stepIds = new Set(orderedSteps.map((step) => step.id));
  const edges: StepGraphEdge[] = [];

  for (const step of orderedSteps) {
    for (const nextStepId of step.next_step_ids) {
      if (stepIds.has(nextStepId)) {
        edges.push({ id: `sequence-${step.id}-${nextStepId}`, from: step.id, to: nextStepId, type: "sequence" });
      }
    }
    if (step.is_fork && step.cloned_from_step_id === null && step.forked_from_step_id && stepIds.has(step.forked_from_step_id)) {
      edges.push({ id: `fork-${step.forked_from_step_id}-${step.id}`, from: step.forked_from_step_id, to: step.id, type: "fork" });
    }
    for (const dependencyId of step.depends_on_step_ids) {
      if (stepIds.has(dependencyId)) {
        edges.push({ id: `dependency-${dependencyId}-${step.id}`, from: dependencyId, to: step.id, type: "dependency" });
      }
    }
    if (step.parent_step_id && stepIds.has(step.parent_step_id)) {
      edges.push({ id: `parent-${step.parent_step_id}-${step.id}`, from: step.parent_step_id, to: step.id, type: "parent" });
    }
    if (step.supersedes_step_id && stepIds.has(step.supersedes_step_id)) {
      edges.push({ id: `supersede-${step.supersedes_step_id}-${step.id}`, from: step.supersedes_step_id, to: step.id, type: "supersede" });
    }
  }

  return { steps: orderedSteps, edges: uniqueEdges(edges) };
}

function layoutStepGraph(steps: Step[]) {
  const graph = buildStepGraph(steps);
  const rows = new Map<number, number>();
  const lanes = new Map<number, number>();
  const displayOrders = new Map<number, number>();
  const stepsById = new Map(graph.steps.map((step) => [step.id, step]));
  const branchRootsBySource = new Map<number, Step[]>();
  for (const step of graph.steps) {
    if (step.is_fork && step.cloned_from_step_id === null && step.forked_from_step_id && stepsById.has(step.forked_from_step_id)) {
      const roots = branchRootsBySource.get(step.forked_from_step_id) ?? [];
      roots.push(step);
      branchRootsBySource.set(step.forked_from_step_id, roots);
    }
  }
  const roots = graph.steps.filter((step) => !step.previous_step_ids.some((id) => stepsById.has(id)) && !(step.is_fork && step.cloned_from_step_id === null && step.forked_from_step_id && stepsById.has(step.forked_from_step_id)));
  const startSteps = (roots.length > 0 ? roots : graph.steps).sort((left, right) => left.step_order - right.step_order || left.position - right.position || left.id - right.id);
  const branchLanes = new Map<string, number>();
  let nextRow = 0;

  function laneFor(step: Step, parentLane: number) {
    if (!step.is_fork && !step.cloned_from_step_id) return parentLane;
    const key = step.clone_batch_id ?? `step-${step.id}`;
    if (!branchLanes.has(key)) {
      branchLanes.set(key, branchLanes.size + 1);
    }
    return branchLanes.get(key) ?? parentLane;
  }

  function visit(step: Step, parentLane = 0, preferredRow?: number) {
    if (rows.has(step.id)) return;
    const row = preferredRow ?? nextRow;
    rows.set(step.id, row);
    lanes.set(step.id, laneFor(step, parentLane));
    displayOrders.set(step.id, row + 1);
    nextRow = Math.max(nextRow, row + 1);
    const successors = step.next_step_ids
      .map((id) => stepsById.get(id))
      .filter((item): item is Step => Boolean(item))
      .sort((left, right) => left.step_order - right.step_order || left.position - right.position || left.id - right.id);
    successors.forEach((successor) => {
      visit(successor, lanes.get(step.id) ?? parentLane, row + 1);
    });
    const branchRoots = (branchRootsBySource.get(step.id) ?? []).sort((left, right) => left.step_order - right.step_order || left.position - right.position || left.id - right.id);
    branchRoots.forEach((branchRoot) => {
      visit(branchRoot, lanes.get(step.id) ?? parentLane, row);
    });
  }

  startSteps.forEach((step) => visit(step));
  graph.steps.forEach((step) => visit(step));

  const nodes = graph.steps.map((step): StepGraphNode => {
    const row = rows.get(step.id) ?? 0;
    const lane = lanes.get(step.id) ?? 0;
    return {
      step,
      column: lane,
      lane: row,
      displayOrder: displayOrders.get(step.id) ?? step.step_order,
      width: workflowNodeWidth,
      height: workflowNodeHeight,
      x: workflowPadding + lane * (workflowNodeWidth + workflowColumnGap),
      y: workflowPadding + row * (workflowNodeHeight + workflowRowGap),
    };
  });

  return { nodes, edges: graph.edges };
}

function edgePath(fromNode: StepGraphNode, toNode: StepGraphNode) {
  if (fromNode.lane === toNode.lane && fromNode.column !== toNode.column) {
    const startX = fromNode.x + fromNode.width;
    const startY = fromNode.y + fromNode.height / 2;
    const endX = toNode.x;
    const endY = toNode.y + toNode.height / 2;
    return `M ${startX} ${startY} L ${endX} ${endY}`;
  }
  const startX = fromNode.x + fromNode.width / 2;
  const startY = fromNode.y + fromNode.height;
  const endX = toNode.x + toNode.width / 2;
  const endY = toNode.y;
  const midY = startY + Math.max(42, (endY - startY) / 2);
  return `M ${startX} ${startY} C ${startX} ${midY}, ${endX} ${midY}, ${endX} ${endY}`;
}

function workflowNodeClass(step: Step, selectedStepId: number | null) {
  const classes = ["workflow-node"];
  if (step.id === selectedStepId) classes.push("workflow-node-selected");
  if (step.status === "running") classes.push("workflow-node-running");
  if (!step.is_active || step.status === "superseded" || step.branch_status === "abandoned" || step.branch_status === "not_selected") classes.push("workflow-node-muted");
  if (step.status === "failed" || step.status === "needs_revision") classes.push("workflow-node-attention");
  return classes.join(" ");
}

function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="error-panel" role="alert">
      <strong>Operation failed</strong>
      <p>{formatErrorMessage(message)}</p>
    </div>
  );
}

function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}

export default function TaskPage() {
  const params = useParams<{ id: string }>();
  const taskId = parseTaskId(params.id);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [runsByStep, setRunsByStep] = useState<RunsByStep>({});
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [sessionMessages, setSessionMessages] = useState<TaskMessage[]>([]);
  const [capabilityInvocations, setCapabilityInvocations] = useState<CapabilityInvocation[]>([]);
  const [comparisonGroups, setComparisonGroups] = useState<Record<number, StepComparisonGroup>>({});
  const [plannerPromptConfig, setPlannerPromptConfig] = useState<PlannerPromptConfig | null>(null);
  const [plannerPromptDraft, setPlannerPromptDraft] = useState("");
  const [isSavingPlannerPrompt, setIsSavingPlannerPrompt] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGeneratingPlan, setIsGeneratingPlan] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());

  async function refresh(options: { showLoading?: boolean } = {}) {
    if (!taskId) return;
    if (options.showLoading !== false) {
      setIsLoading(true);
    }
    const nextDetail = await getTask(taskId);
    const runs = await Promise.all(nextDetail.steps.map(async (step) => [step.id, await listRuns(taskId, step.id)] as const));
    const [nextTimeline, nextArtifacts, nextCapabilityInvocations, nextPlannerPromptConfig] = await Promise.all([listTimeline(taskId), listArtifacts(taskId), listCapabilityInvocations(taskId), getPlannerPrompt()]);
    const comparisonIds = Array.from(new Set(nextDetail.steps.map((step) => step.comparison_group_id).filter((id): id is number => id !== null)));
    const comparisons = await Promise.all(comparisonIds.map(async (id) => [id, await getStepComparison(taskId, id)] as const));
    setDetail(nextDetail);
    setRunsByStep(Object.fromEntries(runs));
    setTimeline(nextTimeline);
    setArtifacts(nextArtifacts);
    setCapabilityInvocations(nextCapabilityInvocations);
    setPlannerPromptConfig(nextPlannerPromptConfig);
    setPlannerPromptDraft(nextPlannerPromptConfig.prompt ?? "");
    setComparisonGroups(Object.fromEntries(comparisons));
    if (options.showLoading !== false) {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    refresh().catch((err) => {
      setError(String(err));
      setIsLoading(false);
    });
  }, [taskId]);

  const shouldPoll = Boolean(
    detail
    && !["completed", "failed", "archived", "cancelled"].includes(detail.task.status)
    && (
      detail.task.status === "running"
      || detail.steps.some((step) => step.status === "running")
      || Object.values(runsByStep).some((runs) => runs.some((run) => run.status === "running"))
    )
  );

  useEffect(() => {
    if (!shouldPoll) return;
    const interval = window.setInterval(() => {
      refresh({ showLoading: false }).catch((err) => setError(String(err)));
    }, 2000);
    return () => window.clearInterval(interval);
  }, [shouldPoll, taskId]);

  useEffect(() => {
    if (!Object.values(runsByStep).some((runs) => runs.some((run) => run.status === "running"))) return;
    const interval = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [runsByStep]);

  async function runAction(action: () => Promise<unknown>, form?: HTMLFormElement) {
    setError(null);
    try {
      await action();
      form?.reset();
      await refresh();
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleAddMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!taskId) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    await runAction(async () => {
      const message = await addTaskMessage(taskId, {
        message: String(data.get("message") ?? ""),
        constraints: String(data.get("constraints") ?? "") || undefined,
      });
      setSessionMessages((items) => [...items, message]);
    }, form);
  }

  async function handleGeneratePlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!taskId) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const steps = [
      { title: String(data.get("step_1_title") ?? ""), objective: String(data.get("step_1_objective") ?? "") },
      { title: String(data.get("step_2_title") ?? ""), objective: String(data.get("step_2_objective") ?? "") },
    ].filter((step) => step.title.trim() && step.objective.trim());
    await runAction(() => generatePlan(taskId, { generation_mode: "manual", reason: String(data.get("reason") ?? "Generated from UI"), steps }), form);
  }

  async function handleAutoGeneratePlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!taskId || isGeneratingPlan || plannerPromptConfig?.configured === false) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setIsGeneratingPlan(true);
    try {
      await runAction(() => generatePlan(taskId, {
        generation_mode: "auto",
        reason: String(data.get("reason") ?? "LLM decomposition"),
        instructions: String(data.get("instructions") ?? "") || undefined,
      }), form);
    } finally {
      setIsGeneratingPlan(false);
    }
  }

  async function handleSavePlannerPrompt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!taskId || isSavingPlannerPrompt) return;
    setError(null);
    setIsSavingPlannerPrompt(true);
    try {
      const nextConfig = await updatePlannerPrompt({ prompt: plannerPromptDraft });
      setPlannerPromptConfig(nextConfig);
      setPlannerPromptDraft(nextConfig.prompt ?? "");
    } catch (err) {
      setError(String(err));
    } finally {
      setIsSavingPlannerPrompt(false);
    }
  }

  async function handleAddStep(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!taskId) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    await runAction(() => createStep(taskId, {
      title: String(data.get("title") ?? ""),
      objective: String(data.get("objective") ?? ""),
      insert_mode: String(data.get("insert_mode") || "append_to_end") as "append_to_end" | "insert_after_step" | "insert_before_step",
      target_step_id: Number(data.get("target_step_id")) || undefined,
      created_reason: String(data.get("created_reason") ?? "") || undefined,
    }), form);
  }

  async function handleAutoRun() {
    if (!taskId) return;
    await runAction(() => autoRunTask(taskId, {
      executor_type: "agent",
      input: { instruction: "Automatically execute all remaining steps.", auto_run: true },
    }));
  }

  if (!taskId) {
    return (
      <main className="stack">
        <Link href="/">Back to tasks</Link>
        <div className="card">Invalid task id.</div>
      </main>
    );
  }

  if (isLoading && !detail) {
    return (
      <main className="stack">
        <Link href="/">Back to tasks</Link>
        <div className="card">Loading task...</div>
      </main>
    );
  }

  if (!detail) {
    return (
      <main className="stack">
        <Link href="/">Back to tasks</Link>
        {error && <ErrorPanel message={error} />}
      </main>
    );
  }

  const activeStepId = nextActionStepId(detail);
  const planApprovedForAutoRun = !["intake", "planning", "waiting_plan_review"].includes(detail.task.status);
  const canAutoRun = activeStepId !== null && planApprovedForAutoRun && !shouldPoll && !["completed", "failed", "archived", "cancelled"].includes(detail.task.status);
  const canCloseTask = !["archived", "cancelled"].includes(detail.task.status);
  const currentStep = detail.current_pointer.step_id ? detail.steps.find((step) => step.id === detail.current_pointer.step_id) : null;

  return (
    <main className="stack">
      <Link href="/">Back to tasks</Link>
      {error && <ErrorPanel message={error} />}

      <section className="card stack">
        <div className="row between">
          <div>
            <h1>{detail.task.title}</h1>
            <p>{detail.task.goal}</p>
          </div>
          <span className="badge">{detail.task.status} · {detail.task.executor_mode === "codex" ? "tmux + Codex" : "text agent"}</span>
        </div>
        {detail.task.constraints && <p><strong>Constraints:</strong> {detail.task.constraints}</p>}
        {detail.task.project_path && <p><strong>Project path:</strong> {detail.task.project_path}</p>}
        {detail.task.codex_tmux_session && <p><strong>tmux session:</strong> <code>{detail.task.codex_tmux_session}</code></p>}
        {detail.task.log_path && <p><strong>Log path:</strong> <code>{detail.task.log_path}</code></p>}
        <div className="progress"><span style={{ width: `${detail.progress.progress_percent}%` }} /></div>
        <p>{detail.progress.progress_percent}% complete · consumed: {formatDuration(detail.progress.consumed_ms)}</p>
        <div className="row secondary-actions">
          <button type="button" onClick={handleAutoRun} disabled={!canAutoRun}>Run all remaining steps automatically</button>
          {canCloseTask && <button type="button" className="secondary" onClick={() => runAction(() => closeTask(taskId, { reason: "Closed from UI", actor_id: "local-user" }))}>Close task</button>}
          {!planApprovedForAutoRun && detail.task.status === "waiting_plan_review" && <span className="badge">Approve the plan before auto-run</span>}
          {shouldPoll && <span className="badge">Auto-updating while LLM runs</span>}
        </div>
        <div className="muted-panel stack">
          <div className="section-heading">
            <h3>Current status</h3>
            <span className="badge">{detail.progress.progress_percent}% complete</span>
          </div>
          {currentStep ? (
            <p><strong>Current step:</strong> step_id: {currentStep.id} · {currentStep.title} · {statusLabel(stepStatusLabels, currentStep.status)}</p>
          ) : (
            <p><strong>Current step:</strong> No step selected yet.</p>
          )}
        </div>
        <h3>Capability summary</h3>
        <p>{detail.capability_invocations_count} capability invocation records.</p>
        {detail.latest_capability_invocations.length > 0 && (
          <details>
            <summary>Show latest capability records</summary>
            <pre>{rawDetails(detail.latest_capability_invocations)}</pre>
          </details>
        )}
      </section>

      <PrimaryActionCard
        detail={detail}
        activeStepId={activeStepId}
        canAutoRun={canAutoRun}
        plannerPromptConfigured={plannerPromptConfig?.configured ?? false}
        isGeneratingPlan={isGeneratingPlan}
        shouldPoll={shouldPoll}
        onApprovePlan={() => runAction(() => approvePlan(taskId))}
        onAutoRun={handleAutoRun}
      />

      <div className="grid detail-grid">
        <section className="stack">
          <NextActions detail={detail} />
          <TaskForms
            taskStatus={detail.task.status}
            isGeneratingPlan={isGeneratingPlan}
            plannerPromptConfig={plannerPromptConfig}
            plannerPromptDraft={plannerPromptDraft}
            isSavingPlannerPrompt={isSavingPlannerPrompt}
            onPlannerPromptDraftChange={setPlannerPromptDraft}
            onSavePlannerPrompt={handleSavePlannerPrompt}
            onAddMessage={handleAddMessage}
            onGeneratePlan={handleGeneratePlan}
            onAutoGeneratePlan={handleAutoGeneratePlan}
            onApprovePlan={() => runAction(() => approvePlan(taskId))}
            onAddStep={handleAddStep}
          />
          <SessionMessages messages={sessionMessages} />
        </section>

        <section className="stack">
          <StepFlowCanvas taskId={taskId} taskStatus={detail.task.status} steps={detail.steps} currentStepId={activeStepId} runsByStep={runsByStep} comparisonGroups={comparisonGroups} refresh={refresh} setError={setError} nowMs={nowMs} />
          <CapabilityInvocations invocations={capabilityInvocations} taskId={taskId} refresh={refresh} setError={setError} />
          <Timeline events={timeline} />
          <Artifacts artifacts={artifacts} />
        </section>
      </div>
    </main>
  );
}

function PrimaryActionCard({
  detail,
  activeStepId,
  canAutoRun,
  plannerPromptConfigured,
  isGeneratingPlan,
  shouldPoll,
  onApprovePlan,
  onAutoRun,
}: {
  detail: TaskDetail;
  activeStepId: number | null;
  canAutoRun: boolean;
  plannerPromptConfigured: boolean;
  isGeneratingPlan: boolean;
  shouldPoll: boolean;
  onApprovePlan: () => void;
  onAutoRun: () => void;
}) {
  let title = "Continue task";
  let copy = detail.next_actions[0]?.label ?? "No immediate action is available.";
  let action: ReactNode = null;

  if (detail.task.status === "intake" || detail.task.status === "planning") {
    title = "Create the plan";
    copy = plannerPromptConfigured ? "Use the Plan task panel below to generate concrete steps from the current prompt." : "Save a planner system prompt first, then generate the plan.";
  } else if (detail.task.status === "waiting_plan_review") {
    title = "Review the plan";
    copy = "Approve the generated plan when it looks right, or regenerate it from the Plan task panel.";
    action = <button type="button" onClick={onApprovePlan}>Approve plan</button>;
  } else if (shouldPoll) {
    title = "Execution is running";
    copy = "The page is refreshing while the current run is active.";
  } else if (activeStepId !== null) {
    title = "Run the next step";
    copy = `Step ${activeStepId} is ready. Select it in the workflow or run all remaining steps automatically.`;
    action = <button type="button" onClick={onAutoRun} disabled={!canAutoRun}>Run all remaining steps</button>;
  } else if (detail.task.status === "completed") {
    title = "Task complete";
    copy = "All active steps are complete.";
  }

  return (
    <section className="primary-action">
      <div>
        <p className="eyebrow">Next operation</p>
        <h2 className="primary-action-title">{title}</h2>
        <p className="primary-action-copy">{copy}</p>
      </div>
      <div className="primary-action-controls">
        {isGeneratingPlan && <span className="badge running-badge">Generating plan</span>}
        {shouldPoll && <span className="badge running-badge">Running</span>}
        {action}
      </div>
    </section>
  );
}

function NextActions({ detail }: { detail: TaskDetail }) {
  const taskActions = detail.next_actions.filter((action) => action.target_type === "task" || action.target_type === "comparison_group");
  if (taskActions.length === 0) {
    return null;
  }
  return (
    <details className="card">
      <summary>Task next actions ({taskActions.length})</summary>
      <div className="stack action-panel">
        {taskActions.map((action) => (
          <div className="item stack" key={`${action.action_type}-${action.api.path}-${JSON.stringify(action.target)}`}>
            <div className="row between">
              <strong>{action.label}</strong>
              <span className="badge">{action.action_type}</span>
            </div>
            <small>{action.api.method} {action.api.path}</small>
          </div>
        ))}
      </div>
    </details>
  );
}

function TaskForms({
  taskStatus,
  isGeneratingPlan,
  plannerPromptConfig,
  plannerPromptDraft,
  isSavingPlannerPrompt,
  onPlannerPromptDraftChange,
  onSavePlannerPrompt,
  onAddMessage,
  onGeneratePlan,
  onAutoGeneratePlan,
  onApprovePlan,
  onAddStep,
}: {
  taskStatus: string;
  isGeneratingPlan: boolean;
  plannerPromptConfig: PlannerPromptConfig | null;
  plannerPromptDraft: string;
  isSavingPlannerPrompt: boolean;
  onPlannerPromptDraftChange: (value: string) => void;
  onSavePlannerPrompt: (event: FormEvent<HTMLFormElement>) => void;
  onAddMessage: (event: FormEvent<HTMLFormElement>) => void;
  onGeneratePlan: (event: FormEvent<HTMLFormElement>) => void;
  onAutoGeneratePlan: (event: FormEvent<HTMLFormElement>) => void;
  onApprovePlan: () => void;
  onAddStep: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const promptMissing = plannerPromptConfig?.configured === false;
  return (
    <section className="card stack">
      <div className="section-heading">
        <h2>Task controls</h2>
        <span className="badge">{taskStatus}</span>
      </div>

      <div className="control-group stack">
        <div className="section-heading">
          <h3>{taskStatus === "waiting_plan_review" ? "Review or regenerate plan" : "Plan task"}</h3>
          <span className="badge">{plannerPromptConfig?.configured ? "prompt configured" : "prompt missing"}</span>
        </div>
        {taskStatus === "waiting_plan_review" && <button type="button" onClick={onApprovePlan}>Approve current plan</button>}
        <form className="stack" onSubmit={onAutoGeneratePlan}>
          <p>Recommended: let the LLM decompose the task into concrete steps.</p>
          {promptMissing && <p className="running-note">Save the planner system prompt before automatic generation.</p>}
          {isGeneratingPlan && <p className="running-note">Planner is generating the step plan now. Please wait...</p>}
          <input name="reason" defaultValue={taskStatus === "waiting_plan_review" ? "Replace plan with LLM decomposition" : "LLM decomposition"} disabled={isGeneratingPlan || promptMissing} />
          <textarea name="instructions" placeholder="Optional planner instructions" disabled={isGeneratingPlan || promptMissing} />
          <button disabled={isGeneratingPlan || promptMissing}>{isGeneratingPlan ? "Generating plan..." : taskStatus === "waiting_plan_review" ? "Regenerate automatically" : "Generate automatically"}</button>
        </form>
      </div>

      <details className="control-group advanced-section" open={!plannerPromptConfig?.configured}>
        <summary>Planner setup</summary>
        <form className="stack action-panel" onSubmit={onSavePlannerPrompt}>
          <div className="row between">
            <strong>Planner system prompt</strong>
            <span className="badge">{plannerPromptConfig?.configured ? "configured" : "not configured"}</span>
          </div>
          <textarea value={plannerPromptDraft} onChange={(event) => onPlannerPromptDraftChange(event.target.value)} placeholder="Enter the system prompt used for automatic plan generation" required />
          {plannerPromptConfig?.updated_at && <small>Last updated: {new Date(plannerPromptConfig.updated_at).toLocaleString()}</small>}
          <button className="secondary" disabled={isSavingPlannerPrompt}>{isSavingPlannerPrompt ? "Saving prompt..." : "Save planner prompt"}</button>
        </form>
      </details>

      <form className="control-group stack" onSubmit={onAddMessage}>
        <h3>Add message</h3>
        <textarea name="message" placeholder="Message" required />
        <textarea name="constraints" placeholder="Updated constraints" />
        <button className="secondary">Add message</button>
      </form>

      <details className="control-group advanced-section">
        <summary>Advanced manual controls</summary>
        <div className="stack action-panel">
          <form className="stack" onSubmit={onGeneratePlan}>
            <h3>Generate plan manually</h3>
            <p>Manual mode uses the fields below exactly; it does not ask the LLM to expand the plan.</p>
            <input name="reason" defaultValue="Initial decomposition" />
            {defaultPlanSteps.map((step, index) => (
              <div className="item stack" key={step.title}>
                <input name={`step_${index + 1}_title`} defaultValue={step.title} required={index === 0} />
                <textarea name={`step_${index + 1}_objective`} defaultValue={step.objective} required={index === 0} />
              </div>
            ))}
            <button className="secondary">Generate manual plan</button>
          </form>

          <form className="stack" onSubmit={onAddStep}>
            <h3>Add step</h3>
            <input name="title" placeholder="Step title" required />
            <textarea name="objective" placeholder="Step objective" required />
            <select name="insert_mode" defaultValue="append_to_end">
              <option value="append_to_end">Append to end</option>
              <option value="insert_after_step">Insert after step</option>
              <option value="insert_before_step">Insert before step</option>
            </select>
            <input name="target_step_id" placeholder="Target step id for insert" />
            <input name="created_reason" placeholder="Created reason" />
            <button className="secondary">Add step</button>
          </form>
        </div>
      </details>
    </section>
  );
}

function SessionMessages({ messages }: { messages: TaskMessage[] }) {
  return (
    <section className="card stack">
      <h2>Messages added this session</h2>
      {messages.length === 0 ? <EmptyState title="No session messages">Messages you add from this page will appear here.</EmptyState> : messages.map((message) => (
        <div className="item" key={message.id}>
          <strong>{message.author_type}</strong>: {message.message}
        </div>
      ))}
    </section>
  );
}

function StepFlowCanvas({
  taskId,
  taskStatus,
  steps,
  currentStepId,
  runsByStep,
  comparisonGroups,
  refresh,
  setError,
  nowMs,
}: {
  taskId: number;
  taskStatus: string;
  steps: Step[];
  currentStepId: number | null;
  runsByStep: RunsByStep;
  comparisonGroups: Record<number, StepComparisonGroup>;
  refresh: () => Promise<void>;
  setError: (value: string | null) => void;
  nowMs: number;
}) {
  const nextStepId = currentStepId;
  const [selectedStepId, setSelectedStepId] = useState<number | null>(() => initialSelectedStepId(steps, currentStepId));

  useEffect(() => {
    if (steps.length === 0) {
      setSelectedStepId(null);
      return;
    }
    if (selectedStepId === null || !steps.some((step) => step.id === selectedStepId)) {
      setSelectedStepId(initialSelectedStepId(steps, currentStepId));
    }
  }, [steps, selectedStepId, currentStepId]);

  async function runStepAction(action: () => Promise<unknown>, form?: HTMLFormElement) {
    setError(null);
    try {
      await action();
      form?.reset();
      await refresh();
    } catch (err) {
      setError(String(err));
    }
  }

  const hasRunningOrReviewStep = steps.some((step) => ["running", "waiting_review"].includes(step.status));
  const { nodes, edges } = layoutStepGraph(steps);
  const nodeById = new Map(nodes.map((node) => [node.step.id, node]));
  const runningNode = nodes.find((node) => node.step.status === "running") ?? null;
  const selectedNode = selectedStepId === null ? null : nodeById.get(selectedStepId) ?? null;
  const selectedStep = selectedNode?.step ?? null;
  const selectedRuns = selectedStep ? runsByStep[selectedStep.id] ?? [] : [];
  const canvasWidth = Math.max(640, ...nodes.map((node) => node.x + node.width + workflowPadding));
  const canvasHeight = Math.max(260, ...nodes.map((node) => node.y + node.height + workflowPadding));

  return (
    <section className="card stack workflow-card">
      <div className="row between workflow-toolbar">
        <h2>Task workflow</h2>
        <div className="row workflow-status-pills">
          {runningNode && <span className="badge running-badge">Running: Step {runningNode.displayOrder} · {runningNode.step.title}</span>}
          {!runningNode && nextStepId !== null && <span className="badge">Next step: {nextStepId}</span>}
        </div>
      </div>

      {steps.length === 0 ? <EmptyState title="No workflow steps">Generate a plan or add the first step to start the workflow.</EmptyState> : (
        <>
          <div className="workflow-canvas-shell">
            <div className="workflow-canvas-scroll">
              <div className="workflow-board" style={{ width: canvasWidth, height: canvasHeight }}>
                <svg className="workflow-edges" width={canvasWidth} height={canvasHeight} viewBox={`0 0 ${canvasWidth} ${canvasHeight}`} aria-hidden="true">
                  <defs>
                    <marker id="workflow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                      <path d="M 0 0 L 10 5 L 0 10 z" />
                    </marker>
                  </defs>
                  {edges.map((edge) => {
                    const fromNode = nodeById.get(edge.from);
                    const toNode = nodeById.get(edge.to);
                    if (!fromNode || !toNode) return null;
                    return <path key={edge.id} className={`workflow-edge workflow-edge-${edge.type}`} d={edgePath(fromNode, toNode)} markerEnd="url(#workflow-arrow)" />;
                  })}
                </svg>

                {nodes.map((node) => {
                  const step = node.step;
                  const stepRuns = runsByStep[step.id] ?? [];
                  const runningRun = stepRuns.find((run) => run.status === "running");
                  return (
                    <div
                      role="button"
                      tabIndex={0}
                      key={step.id}
                      className={workflowNodeClass(step, selectedStepId)}
                      style={{ left: node.x, top: node.y, width: node.width, minHeight: node.height }}
                      onClick={() => setSelectedStepId(step.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setSelectedStepId(step.id);
                        }
                      }}
                    >
                      <div className="row between">
                        <span className="badge">Step {node.displayOrder}</span>
                        <span className={`badge ${step.status === "running" ? "running-badge" : ""}`}>{step.status === "running" ? "Running now" : statusLabel(stepStatusLabels, step.status)}</span>
                      </div>
                      <strong>{step.title}</strong>
                      <p>{step.objective}</p>
                      <small>step_id: {step.id} · runs: {stepRuns.length} · consumed: {formatDuration(stepDisplayDuration(step, stepRuns, nowMs))}</small>
                      {runningRun && <small>Running attempt {runningRun.attempt_number} · {formatDuration(runDisplayDuration(runningRun, nowMs))}</small>}
                      {(step.is_fork || step.comparison_group_id || step.branch_status) && (
                        <small>{step.variant_label ?? (step.is_fork ? "fork" : "variant")} · {step.branch_status ?? "active"}</small>
                      )}
                      {(step.is_selected_variant || step.selected_variant) && <span className="badge">selected variant</span>}
                      <WorkflowNodeActions taskId={taskId} step={step} hasRunningOrReviewStep={hasRunningOrReviewStep} runStepAction={runStepAction} onSelect={() => setSelectedStepId(step.id)} />
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="workflow-detail-panel item stack">
            {selectedStep ? (
              <>
                <div className="row between">
                  <div className="stack">
                    <span className="badge">Step {selectedNode?.displayOrder ?? selectedStep.step_order}</span>
                    <h3>{selectedStep.title}</h3>
                    <p>{selectedStep.objective}</p>
                  </div>
                  <span className="badge">{statusLabel(stepStatusLabels, selectedStep.status)}</span>
                </div>
                {selectedStep.status === "running" && <p className="running-note">{selectedRuns.find((run) => run.status === "running")?.executor_type === "codex" ? "Codex is programming in tmux now. The canvas will update automatically when the hook returns." : "LLM is executing this step now. The canvas will update automatically when it finishes."}</p>}
                <small>
                  step_id: {selectedStep.id} · active: {String(selectedStep.is_active)} · approved_run_id: {selectedStep.approved_run_id ?? "none"} · runs_count: {selectedRuns.length} · consumed: {formatDuration(stepDisplayDuration(selectedStep, selectedRuns, nowMs))}
                </small>
                {selectedStep.comparison_group_id && (
                  <small>
                    variant_label: {selectedStep.variant_label ?? "none"} · branch_status: {selectedStep.branch_status ?? "none"} · comparison_group_id: {selectedStep.comparison_group_id}
                  </small>
                )}
                <StepMutationForms taskId={taskId} step={selectedStep} comparisonGroups={comparisonGroups} runStepAction={runStepAction} />
                <StepRunForms taskId={taskId} taskStatus={taskStatus} step={selectedStep} isNextStep={selectedStep.id === nextStepId} hasRunningOrReviewStep={hasRunningOrReviewStep} runStepAction={runStepAction} />
                {selectedRuns.map((run) => (
                  <RunCard key={run.id} run={run} taskId={taskId} stepId={selectedStep.id} runStepAction={runStepAction} nowMs={nowMs} />
                ))}
                {selectedStep.comparison_group_id && comparisonGroups[selectedStep.comparison_group_id] && (
                  <ComparisonGroupCard group={comparisonGroups[selectedStep.comparison_group_id]} taskId={taskId} runStepAction={runStepAction} />
                )}
              </>
            ) : (
              <EmptyState title="Select a step">Select a workflow node to inspect and operate on that step.</EmptyState>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function WorkflowNodeActions({
  taskId,
  step,
  hasRunningOrReviewStep,
  runStepAction,
  onSelect,
}: {
  taskId: number;
  step: Step;
  hasRunningOrReviewStep: boolean;
  runStepAction: (action: () => Promise<unknown>, form?: HTMLFormElement) => Promise<void>;
  onSelect: () => void;
}) {
  const branchEnabled = canBranchRun(step, hasRunningOrReviewStep);
  const retryEnabled = canRetryInPlace(step, hasRunningOrReviewStep);

  async function runNodeAction(event: MouseEvent<HTMLButtonElement>, action: () => Promise<unknown>) {
    event.stopPropagation();
    onSelect();
    await runStepAction(action);
  }

  return (
    <div className="workflow-node-actions">
      <button
        type="button"
        className="workflow-node-action secondary"
        disabled={!branchEnabled}
        onClick={(event) => {
          event.stopPropagation();
          onSelect();
        }}
      >
        Edit branch request
      </button>
      <button
        type="button"
        className="workflow-node-action secondary"
        disabled={!retryEnabled}
        onClick={(event) => runNodeAction(event, () => retryStep(taskId, step.id, { executor_type: "agent", input: { instruction: "" } }))}
      >
        {retryLabel(step)}
      </button>
    </div>
  );
}

function StepMutationForms({
  taskId,
  step,
  comparisonGroups,
  runStepAction,
}: {
  taskId: number;
  step: Step;
  comparisonGroups: Record<number, StepComparisonGroup>;
  runStepAction: (action: () => Promise<unknown>, form?: HTMLFormElement) => Promise<void>;
}) {
  async function handleEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await runStepAction(() => updateStep(taskId, step.id, {
      title: String(data.get("title") ?? ""),
      objective: String(data.get("objective") ?? ""),
    }));
  }

  async function handleSupersede(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await runStepAction(() => supersedeStep(taskId, step.id, {
      new_step: { title: String(data.get("title") ?? ""), objective: String(data.get("objective") ?? "") },
      reason: String(data.get("reason") ?? "") || undefined,
      actor_id: "local-user",
    }), form);
  }

  async function handleFork(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await runStepAction(() => forkStep(taskId, step.id, {
      variant_label: String(data.get("variant_label") ?? ""),
      title: String(data.get("title") ?? ""),
      objective: String(data.get("objective") ?? ""),
      fork_reason: String(data.get("fork_reason") ?? "") || undefined,
      clone_subtree: data.get("clone_subtree") === "on",
      created_by_type: "human",
      created_by_id: "local-user",
    }), form);
  }

  return (
    <details>
      <summary>Modify this step</summary>
      <div className="stack action-panel">
        <div className="two-column">
          <button type="button" className="secondary" onClick={() => runStepAction(() => skipStep(taskId, step.id, { reason: "Skipped from UI", actor_id: "local-user" }))}>Skip step</button>
          <button type="button" className="secondary" onClick={() => step.comparison_group_id !== null && runStepAction(() => getStepComparison(taskId, step.comparison_group_id as number))} disabled={step.comparison_group_id === null}>Compare variants</button>
          <button type="button" className="secondary" onClick={() => runStepAction(() => abandonStepVariant(taskId, step.id, { reason: "Abandoned from UI", actor_id: "local-user" }))}>Abandon variant</button>
        </div>
        <form className="stack" onSubmit={handleEdit}>
          <input name="title" defaultValue={step.title} placeholder="Step title" />
          <textarea name="objective" defaultValue={step.objective} placeholder="Step objective" />
          <button className="secondary">Save step content</button>
        </form>
        <form className="stack" onSubmit={handleSupersede}>
          <input name="title" placeholder="Replacement title" />
          <textarea name="objective" placeholder="Replacement objective" />
          <input name="reason" placeholder="Supersede reason" />
          <button className="secondary">Supersede step</button>
        </form>
        <form className="stack" onSubmit={handleFork}>
          <input name="variant_label" placeholder="Variant label" />
          <input name="title" placeholder="Fork title" />
          <textarea name="objective" placeholder="Fork objective" />
          <input name="fork_reason" placeholder="Fork reason" />
          <label><input name="clone_subtree" type="checkbox" /> Clone subtree</label>
          <button className="secondary">Fork step</button>
        </form>
        {step.comparison_group_id && comparisonGroups[step.comparison_group_id] && <p>Comparison group loaded below.</p>}
      </div>
    </details>
  );
}

function ComparisonGroupCard({
  group,
  taskId,
  runStepAction,
}: {
  group: StepComparisonGroup;
  taskId: number;
  runStepAction: (action: () => Promise<unknown>, form?: HTMLFormElement) => Promise<void>;
}) {
  return (
    <div className="item stack">
      <div className="row between">
        <strong>Comparison group {group.comparison_group_id}</strong>
        <span className="badge">{group.status}</span>
      </div>
      <small>base_step_id: {group.base_step_id ?? "none"} · selected_step_id: {group.selected_step_id ?? "none"}</small>
      {group.variants.map((variant) => (
        <div className="item" key={variant.step_id}>
          <strong>{variant.variant_label ?? `step ${variant.step_id}`}</strong>
          <small> · step_id: {variant.step_id} · status: {variant.status} · branch_status: {variant.branch_status ?? "none"} · runs: {variant.runs_count} · approved_run_id: {variant.approved_run_id ?? "none"} · artifacts: {variant.artifacts_count}</small>
          <button type="button" className="secondary" onClick={() => runStepAction(() => selectStepVariant(taskId, group.comparison_group_id, { selected_step_id: variant.step_id, note: "Selected from UI", actor_id: "local-user" }))}>Select variant</button>
        </div>
      ))}
      {group.next_actions.length > 0 && (
        <details>
          <summary>Show comparison actions</summary>
          <pre>{rawDetails(group.next_actions)}</pre>
        </details>
      )}
    </div>
  );
}

function StepRunForms({
  taskId,
  taskStatus,
  step,
  isNextStep,
  hasRunningOrReviewStep,
  runStepAction,
}: {
  taskId: number;
  taskStatus: string;
  step: Step;
  isNextStep: boolean;
  hasRunningOrReviewStep: boolean;
  runStepAction: (action: () => Promise<unknown>, form?: HTMLFormElement) => Promise<void>;
}) {
  async function handleStartRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await runStepAction(() => createRun(taskId, step.id, { executor_type: "agent", input: { instruction: String(data.get("instruction") ?? "") } }), form);
  }

  async function handleAutoRunFromStep(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await runStepAction(() => autoRunFromStep(taskId, step.id, {
      executor_type: "agent",
      input: { instruction: String(data.get("instruction") ?? "Automatically execute this branch from the selected step.") },
    }), form);
  }

  async function handleBranchRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await runStepAction(() => rerunStep(taskId, step.id, { executor_type: "agent", input: {}, change_request: String(data.get("change_request") ?? "") || undefined }), form);
  }

  async function handleRetry(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await runStepAction(() => retryStep(taskId, step.id, { executor_type: "agent", input: { instruction: String(data.get("instruction") ?? "") } }), form);
  }

  const planApproved = !["intake", "planning", "waiting_plan_review"].includes(taskStatus);
  const canStart = planApproved && ["pending", "needs_revision", "failed"].includes(step.status) && isNextStep;
  const canAutoRunFromStep = planApproved && ["pending", "needs_revision", "failed"].includes(step.status) && !hasRunningOrReviewStep;
  const canCreateBranchRun = planApproved && canBranchRun(step, hasRunningOrReviewStep);
  const canRetry = planApproved && canRetryInPlace(step, hasRunningOrReviewStep);

  if (!canStart && !canAutoRunFromStep && !canCreateBranchRun && !canRetry) {
    return null;
  }

  return (
    <div className="two-column">
      {canStart && (
        <form className="stack" onSubmit={handleStartRun}>
          {isNextStep && <strong>Next step</strong>}
          <input name="instruction" placeholder="Optional LLM instruction" />
          <button>{isNextStep ? "Run current step" : "Run step"}</button>
        </form>
      )}
      {canAutoRunFromStep && (
        <form className="stack" onSubmit={handleAutoRunFromStep}>
          <small>Runs this step, then continues along this branch only.</small>
          <input name="instruction" placeholder="Optional branch run instruction" />
          <button className="secondary">Run from this step</button>
        </form>
      )}
      {canCreateBranchRun && (
        <form className="stack" onSubmit={handleBranchRun}>
          <small>Creates a new branch from this step and starts it. The change is saved into the branch step objective.</small>
          <input name="change_request" placeholder="Branch change request" />
          <button className="secondary">{branchRunLabel(step)}</button>
        </form>
      )}
      {canRetry && (
        <form className="stack" onSubmit={handleRetry}>
          <small>Creates a new attempt on this same step without opening a branch.</small>
          <input name="instruction" placeholder="Rerun instruction" />
          <button className="secondary">{retryLabel(step)}</button>
        </form>
      )}
    </div>
  );
}

function RunCard({
  run,
  taskId,
  stepId,
  runStepAction,
  nowMs,
}: {
  run: StepRun;
  taskId: number;
  stepId: number;
  runStepAction: (action: () => Promise<unknown>, form?: HTMLFormElement) => Promise<void>;
  nowMs: number;
}) {
  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await runStepAction(() => submitRun(taskId, stepId, run.id, { output: { summary: String(data.get("summary") ?? "") } }), form);
  }

  async function handleCapabilityInvocation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await runStepAction(() => createCapabilityInvocation(taskId, stepId, run.id, {
      capability_id: String(data.get("capability_id") || "generate_report"),
      input: { topic: String(data.get("topic") ?? "") },
      invoked_by_type: String(data.get("invoked_by_type") || "agent"),
      invoked_by_id: "ui-agent",
    }), form);
  }

  return (
    <div className="item stack">
      <div className="row between">
        <strong>Attempt {run.attempt_number}</strong>
        <span className="badge">{run.executor_type} · {statusLabel(runStatusLabels, run.status)}</span>
      </div>
      <small>duration: {formatDuration(runDisplayDuration(run, nowMs))} · started: {run.started_at ?? "not started"} · ended: {run.ended_at ?? "not ended"}</small>
      <p>{runSummary(run)}</p>
      <details>
        <summary>Show raw run details</summary>
        <pre>{rawDetails({ input: run.input, output: run.output, error: run.error })}</pre>
      </details>
      {run.status === "running" && run.executor_type === "human" && (
        <>
          <p>This human run is still running. Submit its output before review.</p>
          <form className="stack" onSubmit={handleSubmit}>
            <input name="summary" placeholder="Output summary" />
            <button>Submit run for review</button>
          </form>
        </>
      )}
      {run.status === "running" && run.executor_type !== "human" && (
        <>
          <p>{run.executor_type === "codex" ? "Codex is running in tmux. The Stop hook will notify this project when it finishes." : "LLM execution is running in the background. This page updates automatically while it runs."}</p>
          <form className="stack" onSubmit={handleCapabilityInvocation}>
            <input name="capability_id" defaultValue="generate_report" />
            <select name="invoked_by_type" defaultValue="agent">
              <option value="human">human</option>
              <option value="agent">agent</option>
              <option value="worker">worker</option>
              <option value="system">system</option>
            </select>
            <input name="topic" placeholder="Capability input topic" />
            <button className="secondary">Record capability invocation</button>
          </form>
        </>
      )}
      {run.status === "submitted" && (
        <>
          <p>This run is ready for review.</p>
          <div className="two-column">
            <button type="button" className="secondary" onClick={() => runStepAction(() => reviewRun(taskId, stepId, run.id, "approved"))}>Approve run</button>
            <button type="button" className="secondary" onClick={() => runStepAction(() => reviewRun(taskId, stepId, run.id, "request_revision"))}>Request revision</button>
          </div>
        </>
      )}
      {run.status === "accepted" && <p>This step is complete.</p>}
      {run.status === "rejected" && <p>This run needs revision. Use rerun on the step card.</p>}
    </div>
  );
}

function CapabilityInvocations({
  invocations,
  taskId,
  refresh,
  setError,
}: {
  invocations: CapabilityInvocation[];
  taskId: number;
  refresh: () => Promise<void>;
  setError: (value: string | null) => void;
}) {
  async function handleUpdate(event: FormEvent<HTMLFormElement>, invocation: CapabilityInvocation) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setError(null);
    try {
      const outputRaw = String(data.get("output") ?? "").trim();
      await updateCapabilityInvocation(taskId, invocation.id, {
        status: String(data.get("status") || invocation.status),
        output: outputRaw ? JSON.parse(outputRaw) : null,
        error: String(data.get("error") ?? "") || null,
        artifacts: [],
      });
      form.reset();
      await refresh();
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <section className="card stack">
      <h2>Capability invocations</h2>
      {invocations.length === 0 ? <EmptyState title="No capability invocations">Tool and capability calls will appear here after a run records them.</EmptyState> : invocations.map((invocation) => (
        <div className="item stack" key={invocation.id}>
          <div className="row between">
            <strong>{invocation.capability_name ?? invocation.capability_id}</strong>
            <span className="badge">{invocation.status}</span>
          </div>
          <small>capability_id: {invocation.capability_id} · step_id: {invocation.step_id ?? "none"} · run_id: {invocation.run_id ?? "none"} · adapter_id: {invocation.adapter_id ?? "none"} · completed_at: {invocation.completed_at ?? "not completed"}</small>
          <p>{capabilitySummary(invocation)}</p>
          <details>
            <summary>Show raw invocation details</summary>
            <pre>{rawDetails({ input: invocation.input, output: invocation.output, error: invocation.error, artifacts: invocation.artifacts })}</pre>
          </details>
          <form className="stack" onSubmit={(event) => handleUpdate(event, invocation)}>
            <select name="status" defaultValue={invocation.status}>
              <option value="pending">pending</option>
              <option value="running">running</option>
              <option value="succeeded">succeeded</option>
              <option value="failed">failed</option>
              <option value="blocked">blocked</option>
              <option value="cancelled">cancelled</option>
            </select>
            <textarea name="output" placeholder='{"summary":"Recorded from UI"}' />
            <input name="error" placeholder="Error message" />
            <button className="secondary">Update invocation</button>
          </form>
        </div>
      ))}
    </section>
  );
}

const timelineEventLabels: Record<string, string> = {
  task_created: "Task created",
  task_message_added: "User message added",
  task_revision_created: "Plan revision created",
  task_plan_generated: "Step plan generated",
  task_plan_approved: "Step plan approved",
  progress_recalculated: "Progress updated",
  step_added: "Step added",
  step_inserted: "Step inserted",
  step_skipped: "Step skipped",
  step_superseded: "Step superseded",
  step_forked: "Step variant forked",
  step_subtree_cloned: "Step subtree cloned",
  step_variant_selected: "Step variant selected",
  comparison_group_created: "Variant comparison created",
  comparison_group_resolved: "Variant comparison resolved",
  step_run_started: "Step run started",
  step_run_submitted: "Step run submitted",
  step_run_reviewed: "Step run reviewed",
  step_approved: "Step approved",
  step_needs_revision: "Step needs revision",
  step_rerun_created: "Step rerun started",
  step_rerun_branch_created: "Rerun branch created",
  step_branch_cloned: "Workflow branch cloned",
  capability_invocation_recorded: "Capability invocation recorded",
  capability_invocation_updated: "Capability invocation updated",
};

function timelineEventLabel(eventType: string) {
  return timelineEventLabels[eventType] ?? eventType.replaceAll("_", " ");
}

function timelineEventSummary(event: TimelineEvent) {
  switch (event.event_type) {
    case "task_created":
      return typeof event.payload.title === "string" ? `Task: ${event.payload.title}` : "Task was created.";
    case "task_message_added":
      return typeof event.payload.message === "string" ? event.payload.message : "A message was added to the task.";
    case "task_revision_created":
      return typeof event.payload.reason === "string" ? event.payload.reason : "A new plan revision was created.";
    case "task_plan_generated":
      return `Generated ${event.payload.step_count ?? "multiple"} steps.`;
    case "task_plan_approved":
      return event.payload.decision === "request_revision" ? "Plan needs revision." : "Plan was approved.";
    case "progress_recalculated":
      return typeof event.payload.progress_percent === "number" ? `Progress is ${event.payload.progress_percent}%.` : "Progress was updated.";
    case "step_added":
    case "step_inserted":
      return typeof event.payload.title === "string" ? event.payload.title : "A step was added.";
    case "step_skipped":
      return typeof event.payload.reason === "string" ? event.payload.reason : "A step was skipped.";
    case "step_run_started":
      return "A step run was started.";
    case "step_run_submitted":
      return "A step run was submitted for review.";
    case "step_run_reviewed":
      return typeof event.payload.decision === "string" ? `Decision: ${event.payload.decision}` : "A step run was reviewed.";
    default:
      return null;
  }
}

function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <section className="card stack">
      <h2>Timeline</h2>
      {events.length === 0 ? <EmptyState title="No timeline events">Task activity will appear here as plans, runs, reviews, and capabilities are recorded.</EmptyState> : events.map((event) => (
        <div className="item" key={event.id}>
          <strong>{timelineEventLabel(event.event_type)}</strong>
          <small> · {new Date(event.created_at).toLocaleString()} · step_id: {event.step_id ?? "none"} · run_id: {event.run_id ?? "none"}</small>
          {timelineEventSummary(event) && <p>{timelineEventSummary(event)}</p>}
        </div>
      ))}
    </section>
  );
}

function Artifacts({ artifacts }: { artifacts: Artifact[] }) {
  return (
    <section className="card stack">
      <h2>Artifacts</h2>
      {artifacts.length === 0 ? <EmptyState title="No artifacts">Files and generated outputs will appear here when a run creates them.</EmptyState> : artifacts.map((artifact) => (
        <div className="item" key={artifact.id}>
          <strong>{artifact.type}: {artifact.name}</strong>
          <small> · capability_invocation_id: {artifact.capability_invocation_id ?? "none"}</small>
          {artifact.uri && <p>{artifact.uri}</p>}
        </div>
      ))}
    </section>
  );
}
