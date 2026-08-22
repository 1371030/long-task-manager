const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export type Task = {
  id: number;
  title: string;
  goal: string;
  constraints: string | null;
  status: string;
  summary: string | null;
  current_revision_id: number | null;
  created_by: string | null;
  executor_mode: string;
  project_path: string | null;
  codex_tmux_session: string | null;
  log_path: string | null;
  created_at: string;
  updated_at: string;
};

export type TaskMessage = {
  id: number;
  task_id: number;
  author_type: string;
  author_id: string | null;
  message: string;
  constraints: string | null;
  created_at: string;
};

export type Step = {
  id: number;
  task_id: number;
  parent_step_id: number | null;
  comparison_group_id: number | null;
  approved_run_id: number | null;
  title: string;
  objective: string;
  status: string;
  position: number;
  depends_on_step_ids: number[];
  previous_step_ids: number[];
  next_step_ids: number[];
  step_order: number;
  is_active: boolean;
  is_dynamic: boolean;
  created_reason: string | null;
  created_by_type: string;
  created_by_id: string | null;
  inserted_after_step_id: number | null;
  supersedes_step_id: number | null;
  superseded_by_step_id: number | null;
  executor_hint: string | null;
  requires_approval: boolean;
  max_attempts: number | null;
  variant_label: string | null;
  selected_variant: boolean | null;
  is_fork: boolean;
  forked_from_step_id: number | null;
  forked_from_run_id: number | null;
  fork_reason: string | null;
  branch_status: string | null;
  cloned_from_step_id: number | null;
  clone_batch_id: string | null;
  is_selected_variant: boolean | null;
  created_at: string;
  updated_at: string;
  consumed_ms: number;
};

export type StepRun = {
  id: number;
  task_id: number;
  step_id: number;
  attempt_number: number;
  executor_type: string;
  executor_ref: string | null;
  status: string;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error: string | null;
  started_at: string | null;
  submitted_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  created_at: string;
  updated_at: string;
};

export type NextAction = {
  action_type: string;
  target_type: string;
  target: Record<string, number | null>;
  label: string;
  api: { method: string; path: string };
  requires_user_input: boolean;
  input_schema: Record<string, unknown>;
};

export type CapabilityInvocationSummary = {
  id: number;
  step_id: number | null;
  run_id: number | null;
  capability_id: string;
  capability_name: string | null;
  status: string;
  created_at: string;
  completed_at: string | null;
};

export type TaskDetail = {
  task: Task;
  steps: Step[];
  progress: {
    active_steps_total: number;
    approved_or_skipped_active_steps: number;
    progress_percent: number;
    consumed_ms: number;
  };
  current_pointer: {
    task_id: number;
    step_id: number | null;
    run_id: number | null;
    capability_invocation_id: number | null;
  };
  next_actions: NextAction[];
  capability_invocations_count: number;
  latest_capability_invocations: CapabilityInvocationSummary[];
};

export type StepVariantSummary = {
  step_id: number;
  variant_label: string | null;
  status: string;
  branch_status: string | null;
  runs_count: number;
  approved_run_id: number | null;
  artifacts_count: number;
  metrics: Record<string, number>;
};

export type StepComparisonGroup = {
  comparison_group_id: number;
  task_id: number;
  base_step_id: number | null;
  status: string;
  selected_step_id: number | null;
  resolved_at: string | null;
  variants: StepVariantSummary[];
  next_actions: NextAction[];
};

export type StepForkResponse = {
  comparison_group_id: number;
  forked_step_id: number;
  cloned_steps_count: number;
};

export type StepRerunBranchResponse = {
  comparison_group_id: number | null;
  forked_step_id: number;
  cloned_steps_count: number;
};

export type CapabilityDefinition = {
  capability_id: string;
  name: string;
  description: string;
  adapter_id: string;
  handler_name: string;
  requires_approval: boolean;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
};

export type CapabilityInvocationArtifact = {
  type: string;
  name: string;
  uri?: string | null;
  metadata: Record<string, unknown>;
};

export type CapabilityInvocation = {
  id: number;
  task_id: number;
  step_id: number | null;
  run_id: number | null;
  invoked_by_type: string;
  invoked_by_id: string | null;
  capability_id: string;
  capability_name: string | null;
  adapter_id: string | null;
  handler_name: string | null;
  status: string;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
  duration_ms: number | null;
  artifacts: CapabilityInvocationArtifact[];
  created_at: string;
  completed_at: string | null;
  ended_at: string | null;
};

export type TimelineEvent = {
  id: number;
  task_id: number;
  step_id: number | null;
  run_id: number | null;
  capability_invocation_id: number | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type Artifact = {
  id: number;
  task_id: number;
  step_id: number | null;
  run_id: number | null;
  capability_invocation_id: number | null;
  type: string;
  name: string;
  uri: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type PlannerPromptConfig = {
  prompt: string | null;
  configured: boolean;
  updated_at: string | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export function getPlannerPrompt() {
  return request<PlannerPromptConfig>("/settings/planner-prompt");
}

export function updatePlannerPrompt(payload: { prompt: string }) {
  return request<PlannerPromptConfig>("/settings/planner-prompt", { method: "PATCH", body: JSON.stringify(payload) });
}

export function listCapabilities() {
  return request<CapabilityDefinition[]>("/capabilities");
}

export function listCapabilityInvocations(taskId: number) {
  return request<CapabilityInvocation[]>(`/tasks/${taskId}/capability-invocations`);
}

export function createCapabilityInvocation(taskId: number, stepId: number, runId: number, payload: { capability_id: string; input: Record<string, unknown>; invoked_by_type: string; invoked_by_id?: string }) {
  return request<CapabilityInvocation>(`/tasks/${taskId}/steps/${stepId}/runs/${runId}/capability-invocations`, { method: "POST", body: JSON.stringify(payload) });
}

export function updateCapabilityInvocation(taskId: number, invocationId: number, payload: { status: string; output?: Record<string, unknown> | null; error?: string | null; duration_ms?: number | null; artifacts?: CapabilityInvocationArtifact[] }) {
  return request<CapabilityInvocation>(`/tasks/${taskId}/capability-invocations/${invocationId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function listTasks() {
  return request<Task[]>("/tasks");
}

export function createTask(payload: { title: string; goal: string; constraints?: string; initial_message?: string; executor_mode?: "agent" | "codex"; project_path?: string }) {
  return request<Task>("/tasks", { method: "POST", body: JSON.stringify(payload) });
}

export function getTask(taskId: number) {
  return request<TaskDetail>(`/tasks/${taskId}`);
}

export function closeTask(taskId: number, payload: { reason?: string; actor_id?: string }) {
  return request<TaskDetail>(`/tasks/${taskId}/close`, { method: "POST", body: JSON.stringify(payload) });
}

export function addTaskMessage(taskId: number, payload: { message: string; constraints?: string }) {
  return request<TaskMessage>(`/tasks/${taskId}/messages`, { method: "POST", body: JSON.stringify(payload) });
}

export type GeneratePlanPayload =
  | { generation_mode?: "manual"; reason?: string; steps: Array<{ title: string; objective: string }>; instructions?: string }
  | { generation_mode: "auto"; reason?: string; instructions?: string; steps?: Array<{ title: string; objective: string }> };

export function generatePlan(taskId: number, payload: GeneratePlanPayload) {
  return request<TaskDetail>(`/tasks/${taskId}/generate-plan`, { method: "POST", body: JSON.stringify(payload) });
}

export function approvePlan(taskId: number) {
  return request<TaskDetail>(`/tasks/${taskId}/approve-plan`, { method: "POST", body: JSON.stringify({ decision: "approved" }) });
}

export type StepCreatePayload = {
  title: string;
  objective: string;
  insert_mode?: "append_to_end" | "insert_after_step" | "insert_before_step";
  target_step_id?: number;
  parent_step_id?: number;
  created_reason?: string;
  executor_hint?: string;
};

export type StepUpdatePayload = {
  title?: string;
  objective?: string;
};

export function createStep(taskId: number, payload: StepCreatePayload) {
  return request<Step>(`/tasks/${taskId}/steps`, { method: "POST", body: JSON.stringify(payload) });
}

export function updateStep(taskId: number, stepId: number, payload: StepUpdatePayload) {
  return request<Step>(`/tasks/${taskId}/steps/${stepId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function listSteps(taskId: number) {
  return request<Step[]>(`/tasks/${taskId}/steps`);
}

export function skipStep(taskId: number, stepId: number, payload: { reason?: string; actor_id?: string }) {
  return request<Step>(`/tasks/${taskId}/steps/${stepId}/skip`, { method: "POST", body: JSON.stringify(payload) });
}

export function supersedeStep(taskId: number, stepId: number, payload: { new_step: { title: string; objective: string }; reason?: string; actor_id?: string }) {
  return request<Step>(`/tasks/${taskId}/steps/${stepId}/supersede`, { method: "POST", body: JSON.stringify(payload) });
}

export function forkStep(taskId: number, stepId: number, payload: { variant_label: string; title: string; objective: string; fork_reason?: string; clone_subtree?: boolean; created_by_type?: string; created_by_id?: string }) {
  return request<StepForkResponse>(`/tasks/${taskId}/steps/${stepId}/fork`, { method: "POST", body: JSON.stringify(payload) });
}

export function getStepComparison(taskId: number, comparisonGroupId: number) {
  return request<StepComparisonGroup>(`/tasks/${taskId}/step-comparisons/${comparisonGroupId}`);
}

export function selectStepVariant(taskId: number, comparisonGroupId: number, payload: { selected_step_id: number; note?: string; actor_id?: string }) {
  return request<StepComparisonGroup>(`/tasks/${taskId}/step-comparisons/${comparisonGroupId}/select`, { method: "POST", body: JSON.stringify(payload) });
}

export function abandonStepVariant(taskId: number, stepId: number, payload: { reason?: string; actor_id?: string }) {
  return request<Step>(`/tasks/${taskId}/steps/${stepId}/abandon-variant`, { method: "POST", body: JSON.stringify(payload) });
}

export function listRuns(taskId: number, stepId: number) {
  return request<StepRun[]>(`/tasks/${taskId}/steps/${stepId}/runs`);
}

export function createRun(taskId: number, stepId: number, payload: { executor_type: string; input: Record<string, unknown> }) {
  return request<StepRun>(`/tasks/${taskId}/steps/${stepId}/runs`, { method: "POST", body: JSON.stringify(payload) });
}

export type AutoRunResponse = {
  task_id: number;
  started: boolean;
  step_id: number | null;
  run_id: number | null;
  message: string;
};

export function autoRunTask(taskId: number, payload: { executor_type?: string; executor_ref?: string; input?: Record<string, unknown> }) {
  return request<AutoRunResponse>(`/tasks/${taskId}/auto-run`, { method: "POST", body: JSON.stringify(payload) });
}

export function autoRunFromStep(taskId: number, stepId: number, payload: { executor_type?: string; executor_ref?: string; input?: Record<string, unknown> }) {
  return request<AutoRunResponse>(`/tasks/${taskId}/steps/${stepId}/auto-run`, { method: "POST", body: JSON.stringify(payload) });
}

export function submitRun(taskId: number, stepId: number, runId: number, payload: { output: Record<string, unknown>; artifacts?: unknown[] }) {
  return request<StepRun>(`/tasks/${taskId}/steps/${stepId}/runs/${runId}/submit`, { method: "POST", body: JSON.stringify(payload) });
}

export function reviewRun(taskId: number, stepId: number, runId: number, decision: "approved" | "request_revision") {
  return request(`/tasks/${taskId}/steps/${stepId}/runs/${runId}/review`, { method: "POST", body: JSON.stringify({ decision }) });
}

export function rerunStep(taskId: number, stepId: number, payload: { executor_type: string; input: Record<string, unknown>; change_request?: string }) {
  return request<StepRerunBranchResponse>(`/tasks/${taskId}/steps/${stepId}/rerun`, { method: "POST", body: JSON.stringify(payload) });
}

export function retryStep(taskId: number, stepId: number, payload: { executor_type: string; input: Record<string, unknown> }) {
  return request<StepRun>(`/tasks/${taskId}/steps/${stepId}/retry`, { method: "POST", body: JSON.stringify(payload) });
}

export function listTimeline(taskId: number) {
  return request<TimelineEvent[]>(`/tasks/${taskId}/timeline`);
}

export function listArtifacts(taskId: number) {
  return request<Artifact[]>(`/tasks/${taskId}/artifacts`);
}
