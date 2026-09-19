from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

TaskStatus = Literal[
    "intake",
    "planning",
    "waiting_plan_review",
    "planned",
    "running",
    "waiting_review",
    "needs_revision",
    "blocked",
    "failed",
    "completed",
    "archived",
    "cancelled",
]
StepStatus = Literal["pending", "running", "waiting_review", "needs_revision", "approved", "failed", "skipped", "superseded"]
BranchStatus = Literal["active", "selected", "not_selected", "superseded", "abandoned"]
ComparisonGroupStatus = Literal["open", "comparing", "resolved", "cancelled"]
InsertMode = Literal["append_to_end", "insert_after_step", "insert_before_step", "insert_after_current", "insert_before_next"]
RunStatus = Literal["running", "submitted", "accepted", "rejected", "failed", "cancelled"]
ExecutorType = Literal["human", "agent", "worker", "system", "codex"]
CapabilityInvokerType = Literal["human", "agent", "worker", "system"]
CapabilityInvocationStatus = Literal["pending", "running", "succeeded", "failed", "blocked", "cancelled"]
ReviewDecision = Literal["approved", "request_revision"]
PlanReviewDecision = Literal["approved", "request_revision"]
ProgressReviewClassification = Literal["ahead", "on_track", "behind"]
ProgressReviewDecision = Literal["keep_plan", "adjust_plan"]


class NextActionApi(BaseModel):
    method: str
    path: str


class NextAction(BaseModel):
    action_type: str
    target_type: str
    target: dict[str, int | None]
    label: str
    api: NextActionApi
    requires_user_input: bool
    input_schema: dict[str, Any] = Field(default_factory=dict)


class CurrentPointer(BaseModel):
    task_id: int
    step_id: int | None = None
    run_id: int | None = None
    capability_invocation_id: int | None = None


class ProgressSummary(BaseModel):
    active_steps_total: int
    approved_or_skipped_active_steps: int
    progress_percent: float
    consumed_ms: int = 0


class TaskCreate(BaseModel):
    title: str
    goal: str
    constraints: str | None = None
    initial_message: str | None = None
    created_by: str | None = "user"
    executor_mode: Literal["agent", "codex"] = "agent"
    project_path: str | None = None

    @model_validator(mode="after")
    def validate_project_path(self) -> "TaskCreate":
        if self.executor_mode == "codex" and not (self.project_path or "").strip():
            raise ValueError("project_path is required when executor_mode is codex")
        return self


class TaskCloseRequest(BaseModel):
    reason: str | None = None
    actor_id: str | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    goal: str
    constraints: str | None = None
    status: str
    summary: str | None = None
    current_revision_id: int | None = None
    created_by: str | None = None
    executor_mode: str = "agent"
    project_path: str | None = None
    codex_tmux_session: str | None = None
    log_path: str | None = None
    created_at: datetime
    updated_at: datetime


class TaskMessageCreate(BaseModel):
    message: str
    constraints: str | None = None
    author_type: ExecutorType = "human"
    author_id: str | None = None


class TaskMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    author_type: str
    author_id: str | None = None
    message: str
    constraints: str | None = None
    created_at: datetime


class PlanStepCreate(BaseModel):
    title: str
    objective: str = Field(validation_alias=AliasChoices("objective", "description"))
    parent_step_id: int | None = None
    position: int | None = None


class PlannerPromptRead(BaseModel):
    prompt: str | None = None
    configured: bool
    updated_at: datetime | None = None


class PlannerPromptUpdate(BaseModel):
    prompt: str = Field(min_length=1, max_length=50000)

    @model_validator(mode="after")
    def validate_prompt(self) -> "PlannerPromptUpdate":
        if not self.prompt.strip():
            raise ValueError("planner prompt cannot be blank")
        return self


class GeneratePlanRequest(BaseModel):
    generation_mode: Literal["manual", "auto"] = "manual"
    steps: list[PlanStepCreate] | None = None
    reason: str = "Generated plan"
    instructions: str | None = None

    @model_validator(mode="after")
    def validate_generation_mode(self) -> "GeneratePlanRequest":
        if self.generation_mode == "manual" and not self.steps:
            raise ValueError("manual plan generation requires at least one step")
        return self


class ApprovePlanRequest(BaseModel):
    decision: PlanReviewDecision = "approved"
    comment: str | None = None
    reviewed_by_type: ExecutorType = "human"
    reviewed_by_id: str | None = None


class StepCreate(BaseModel):
    title: str
    objective: str = Field(validation_alias=AliasChoices("objective", "description"))
    parent_step_id: int | None = None
    position: int | None = None
    step_order: int | None = None
    insert_mode: InsertMode = "append_to_end"
    target_step_id: int | None = None
    depends_on_step_ids: list[int] = Field(default_factory=list)
    created_reason: str | None = None
    created_by_type: ExecutorType = "human"
    created_by_id: str | None = None
    executor_hint: str | None = None
    requires_approval: bool = True
    max_attempts: int | None = None


class StepPatchRequest(BaseModel):
    title: str | None = None
    objective: str | None = Field(default=None, validation_alias=AliasChoices("objective", "description"))
    step_order: int | None = None
    depends_on_step_ids: list[int] | None = None
    executor_hint: str | None = None
    requires_approval: bool | None = None
    max_attempts: int | None = None


class StepSkipRequest(BaseModel):
    reason: str | None = None
    actor_id: str | None = None


class SupersedeStepCreate(BaseModel):
    title: str
    objective: str = Field(validation_alias=AliasChoices("objective", "description"))
    depends_on_step_ids: list[int] | None = None
    executor_hint: str | None = None
    requires_approval: bool = True
    max_attempts: int | None = None


class StepSupersedeRequest(BaseModel):
    new_step: SupersedeStepCreate
    reason: str | None = None
    actor_id: str | None = None


class StepForkRequest(BaseModel):
    variant_label: str
    title: str
    objective: str = Field(validation_alias=AliasChoices("objective", "description"))
    fork_reason: str | None = None
    clone_subtree: bool = False
    forked_from_run_id: int | None = None
    created_by_type: ExecutorType = "human"
    created_by_id: str | None = None


class StepVariantSelectRequest(BaseModel):
    selected_step_id: int
    note: str | None = None
    actor_id: str | None = None


class StepVariantAbandonRequest(BaseModel):
    reason: str | None = None
    actor_id: str | None = None


class StepVariantSummary(BaseModel):
    step_id: int
    variant_label: str | None = None
    status: str
    branch_status: str | None = None
    runs_count: int
    approved_run_id: int | None = None
    artifacts_count: int
    metrics: dict[str, int]


class StepComparisonGroupRead(BaseModel):
    comparison_group_id: int
    task_id: int
    base_step_id: int | None = None
    status: str
    selected_step_id: int | None = None
    resolved_at: datetime | None = None
    variants: list[StepVariantSummary]
    next_actions: list[NextAction] = Field(default_factory=list)


class StepForkResponse(BaseModel):
    comparison_group_id: int
    forked_step_id: int
    cloned_steps_count: int


class StepRerunBranchRequest(BaseModel):
    executor_type: ExecutorType
    executor_ref: str | None = Field(default=None, validation_alias=AliasChoices("executor_ref", "executor_id"))
    input: dict[str, Any] = Field(default_factory=dict)
    variant_label: str | None = None
    title: str | None = None
    objective: str | None = Field(default=None, validation_alias=AliasChoices("objective", "description"))
    change_request: str | None = None
    fork_reason: str | None = None
    created_by_type: ExecutorType = "human"
    created_by_id: str | None = None


class StepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    parent_step_id: int | None = None
    comparison_group_id: int | None = None
    approved_run_id: int | None = None
    title: str
    objective: str
    status: str
    position: int
    depends_on_step_ids: list[int] = Field(default_factory=list)
    previous_step_ids: list[int] = Field(default_factory=list)
    next_step_ids: list[int] = Field(default_factory=list)
    step_order: int
    is_active: bool
    is_dynamic: bool
    created_reason: str | None = None
    created_by_type: str
    created_by_id: str | None = None
    inserted_after_step_id: int | None = None
    supersedes_step_id: int | None = None
    superseded_by_step_id: int | None = None
    executor_hint: str | None = None
    requires_approval: bool
    max_attempts: int | None = None
    variant_label: str | None = None
    selected_variant: bool | None = None
    is_fork: bool
    forked_from_step_id: int | None = None
    forked_from_run_id: int | None = None
    fork_reason: str | None = None
    branch_status: str | None = None
    cloned_from_step_id: int | None = None
    clone_batch_id: str | None = None
    is_selected_variant: bool | None = None
    consumed_ms: int = 0
    created_at: datetime
    updated_at: datetime


class StepRunCreate(BaseModel):
    executor_type: ExecutorType
    executor_ref: str | None = Field(default=None, validation_alias=AliasChoices("executor_ref", "executor_id"))
    input: dict[str, Any] = Field(default_factory=dict)


class AutoRunRequest(BaseModel):
    executor_type: ExecutorType = "agent"
    executor_ref: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)


class AutoRunResponse(BaseModel):
    task_id: int
    started: bool
    step_id: int | None = None
    run_id: int | None = None
    message: str


class StepRunSubmit(BaseModel):
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class StepRunReview(BaseModel):
    decision: ReviewDecision
    comment: str | None = Field(default=None, validation_alias=AliasChoices("comment", "note"))
    reviewed_by_type: ExecutorType = "human"
    reviewed_by_id: str | None = None


class StepRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    step_id: int
    attempt_number: int
    executor_type: str
    executor_ref: str | None = None
    status: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime
    updated_at: datetime


class StepRerunBranchResponse(BaseModel):
    comparison_group_id: int | None = None
    forked_step_id: int
    cloned_steps_count: int


class ProgressReviewCreate(BaseModel):
    expected_progress_percent: float = Field(ge=0, le=100)
    created_by_type: ExecutorType = "human"
    created_by_id: str | None = None


class ProgressReviewDecisionCreate(BaseModel):
    decision: ProgressReviewDecision
    note: str | None = None
    decided_by_type: ExecutorType = "human"
    decided_by_id: str | None = None


class ProgressReviewSnapshot(BaseModel):
    active_steps_total: int
    approved_or_skipped_active_steps: int
    consumed_ms: int
    step_status_counts: dict[str, int]
    run_status_counts: dict[str, int]
    retry_count: int
    dynamic_active_steps: int


class ProgressReviewObservation(BaseModel):
    code: str
    message: str
    target_step_id: int | None = None


class ProgressReviewSuggestion(BaseModel):
    action_type: str
    message: str
    target_step_id: int | None = None
    api_path: str | None = None


class ProgressReviewRead(BaseModel):
    id: int
    task_id: int
    previous_review_id: int | None = None
    expected_progress_percent: float
    actual_progress_percent: float
    variance_percentage_points: float
    classification: ProgressReviewClassification
    snapshot: ProgressReviewSnapshot
    observations: list[ProgressReviewObservation]
    suggestions: list[ProgressReviewSuggestion]
    decision: ProgressReviewDecision | None = None
    decision_note: str | None = None
    decided_by_type: str | None = None
    decided_by_id: str | None = None
    decided_at: datetime | None = None
    created_by_type: str
    created_by_id: str | None = None
    created_at: datetime


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    step_id: int | None = None
    run_id: int | None = None
    decision: str
    comment: str | None = None
    reviewed_by_type: str
    reviewed_by_id: str | None = None
    created_at: datetime


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    step_id: int | None = None
    run_id: int | None = None
    capability_invocation_id: int | None = None
    type: str
    name: str
    uri: str | None = None
    metadata: dict[str, Any]
    created_at: datetime


class ArtifactCreate(BaseModel):
    type: str
    name: str
    uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodexRunCallback(BaseModel):
    task_id: int
    step_id: int
    run_id: int
    attempt_number: int
    status: Literal["completed", "failed"]
    summary: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactCreate] = Field(default_factory=list)
    error: str | None = None


class CodexTaskHookCallback(BaseModel):
    task_id: int
    status: Literal["completed", "failed"]
    summary: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactCreate] = Field(default_factory=list)
    error: str | None = None


class CapabilityDefinitionRead(BaseModel):
    capability_id: str
    name: str
    description: str
    adapter_id: str
    handler_name: str
    requires_approval: bool
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class CapabilityInvocationCreate(BaseModel):
    invoked_by_type: CapabilityInvokerType
    invoked_by_id: str | None = None
    capability_id: str
    input: dict[str, Any] = Field(default_factory=dict)


class CapabilityInvocationUpdate(BaseModel):
    status: CapabilityInvocationStatus
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int | None = None
    artifacts: list[ArtifactCreate] = Field(default_factory=list)


class CapabilityInvocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    step_id: int | None = None
    run_id: int | None = None
    invoked_by_type: str
    invoked_by_id: str | None = None
    capability_id: str
    capability_name: str | None = None
    adapter_id: str | None = None
    handler_name: str | None = None
    status: str
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    completed_at: datetime | None = None
    ended_at: datetime | None = None


class CapabilityInvocationSummary(BaseModel):
    id: int
    step_id: int | None = None
    run_id: int | None = None
    capability_id: str
    capability_name: str | None = None
    status: str
    created_at: datetime
    completed_at: datetime | None = None


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    step_id: int | None = None
    run_id: int | None = None
    capability_invocation_id: int | None = None
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class TaskLogEntry(BaseModel):
    id: str
    timestamp: datetime | None = None
    scope: str
    event_type: str
    title: str
    message: str | None = None
    task_id: int
    step_id: int | None = None
    run_id: int | None = None
    capability_invocation_id: int | None = None
    artifact_id: int | None = None
    status: str | None = None
    duration_ms: int | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    redacted: bool = False



class TaskDetailResponse(BaseModel):
    task: TaskRead
    steps: list[StepRead]
    progress: ProgressSummary
    current_pointer: CurrentPointer
    next_actions: list[NextAction]
    capability_invocations_count: int = 0
    latest_capability_invocations: list[CapabilityInvocationSummary] = Field(default_factory=list)


WbsNodeType = Literal["work", "milestone"]
WbsMilestoneStatus = Literal["open", "completed"]
WbsNodeStatus = Literal["not_started", "in_progress", "blocked", "completed"]
WbsProposalStatus = Literal["draft", "approved", "rejected"]
WbsProposalDecision = Literal["approved", "rejected"]


class WbsNodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    node_type: WbsNodeType = "work"
    position: int = Field(default=1, ge=1)
    parent_id: int | None = None
    execution_task_id: int | None = None
    created_by_id: str | None = None


class WbsNodeRead(BaseModel):
    id: int
    root_id: int
    parent_id: int | None = None
    execution_task_id: int | None = None
    node_type: WbsNodeType
    title: str
    description: str | None = None
    position: int
    depth: int
    is_active: bool
    version: int
    status: WbsNodeStatus
    progress_percent: float
    child_ids: list[int] = Field(default_factory=list)
    milestone_ids: list[int] = Field(default_factory=list)
    blocked_by_node_ids: list[int] = Field(default_factory=list)
    excluded_from_rollup: bool = False
    exclusion_reason: str | None = None


class WbsMilestoneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    criteria: str = Field(min_length=1)
    created_by_id: str | None = None


class WbsMilestonePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    criteria: str | None = Field(default=None, min_length=1)


class WbsMilestoneRead(BaseModel):
    id: int
    node_id: int
    title: str
    criteria: str
    status: WbsMilestoneStatus
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WbsDependencyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predecessor_id: int
    successor_id: int
    reason: str | None = None
    created_by_id: str | None = None


class WbsDependencyRead(BaseModel):
    id: int
    predecessor_id: int
    successor_id: int
    reason: str | None = None
    created_at: datetime


class WbsCriticalPathHint(BaseModel):
    node_ids: list[int] = Field(default_factory=list)
    length: int


class WbsRollupSummary(BaseModel):
    progress_percent: float
    status: WbsNodeStatus
    reportable_node_count: int
    excluded_node_count: int
    exclusion_reasons: list[str] = Field(default_factory=list)


class WbsTreeRead(BaseModel):
    root_id: int
    version: int
    nodes: list[WbsNodeRead]
    milestones: list[WbsMilestoneRead]
    dependencies: list[WbsDependencyRead]
    rollup: WbsRollupSummary
    critical_path: WbsCriticalPathHint


class WbsNodeChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    parent_id: int | None = None
    execution_task_id: int | None = None
    node_type: WbsNodeType
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    position: int = Field(ge=1)
    is_active: bool = True


class WbsDependencyChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predecessor_id: int
    successor_id: int
    reason: str | None = None


class WbsChangeSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[WbsNodeChange]
    dependencies: list[WbsDependencyChange] = Field(default_factory=list)


class WbsChangeProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["update_nodes", "archive_nodes", "add_child", "add_dependency"] = "update_nodes"
    after: WbsChangeSnapshot
    reason: str | None = None
    created_by_id: str | None = None


class WbsChangeProposalDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: WbsProposalDecision
    note: str | None = None
    decided_by_id: str | None = None


class WbsChangeProposalRead(BaseModel):
    id: int
    root_id: int
    base_version: int
    operation: str
    reason: str | None = None
    before: WbsChangeSnapshot
    after: WbsChangeSnapshot
    status: WbsProposalStatus
    decided_by_id: str | None = None
    decision_note: str | None = None
    decided_at: datetime | None = None
    created_by_id: str | None = None
    created_at: datetime
