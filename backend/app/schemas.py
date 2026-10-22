import typing
from datetime import date, datetime
from decimal import Decimal
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
    target: dict[str, typing.Optional[int]]
    label: str
    api: NextActionApi
    requires_user_input: bool
    input_schema: dict[str, Any] = Field(default_factory=dict)


class CurrentPointer(BaseModel):
    task_id: int
    step_id: typing.Optional[int] = None
    run_id: typing.Optional[int] = None
    capability_invocation_id: typing.Optional[int] = None


class ProgressSummary(BaseModel):
    active_steps_total: int
    approved_or_skipped_active_steps: int
    progress_percent: float
    consumed_ms: int = 0


class TaskCreate(BaseModel):
    title: str
    goal: str
    constraints: typing.Optional[str] = None
    initial_message: typing.Optional[str] = None
    created_by: typing.Optional[str] = "user"
    executor_mode: Literal["agent", "codex"] = "agent"
    project_path: typing.Optional[str] = None

    @model_validator(mode="after")
    def validate_project_path(self) -> "TaskCreate":
        if self.executor_mode == "codex" and not (self.project_path or "").strip():
            raise ValueError("project_path is required when executor_mode is codex")
        return self


class TaskCloseRequest(BaseModel):
    reason: typing.Optional[str] = None
    actor_id: typing.Optional[str] = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    goal: str
    constraints: typing.Optional[str] = None
    status: str
    summary: typing.Optional[str] = None
    current_revision_id: typing.Optional[int] = None
    created_by: typing.Optional[str] = None
    executor_mode: str = "agent"
    project_path: typing.Optional[str] = None
    codex_tmux_session: typing.Optional[str] = None
    log_path: typing.Optional[str] = None
    created_at: datetime
    updated_at: datetime


class TaskMessageCreate(BaseModel):
    message: str
    constraints: typing.Optional[str] = None
    author_type: ExecutorType = "human"
    author_id: typing.Optional[str] = None


class TaskMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    author_type: str
    author_id: typing.Optional[str] = None
    message: str
    constraints: typing.Optional[str] = None
    created_at: datetime


class PlanStepCreate(BaseModel):
    title: str
    objective: str = Field(validation_alias=AliasChoices("objective", "description"))
    parent_step_id: typing.Optional[int] = None
    position: typing.Optional[int] = None
    estimate_category: typing.Optional[str] = None


class PlannerPromptRead(BaseModel):
    prompt: typing.Optional[str] = None
    configured: bool
    updated_at: typing.Optional[datetime] = None


class PlannerPromptUpdate(BaseModel):
    prompt: str = Field(min_length=1, max_length=50000)

    @model_validator(mode="after")
    def validate_prompt(self) -> "PlannerPromptUpdate":
        if not self.prompt.strip():
            raise ValueError("planner prompt cannot be blank")
        return self


class GeneratePlanRequest(BaseModel):
    generation_mode: Literal["manual", "auto"] = "manual"
    steps: typing.Optional[list[PlanStepCreate]] = None
    reason: str = "Generated plan"
    instructions: typing.Optional[str] = None

    @model_validator(mode="after")
    def validate_generation_mode(self) -> "GeneratePlanRequest":
        if self.generation_mode == "manual" and not self.steps:
            raise ValueError("manual plan generation requires at least one step")
        return self


class ApprovePlanRequest(BaseModel):
    decision: PlanReviewDecision = "approved"
    comment: typing.Optional[str] = None
    reviewed_by_type: ExecutorType = "human"
    reviewed_by_id: typing.Optional[str] = None


class StepCreate(BaseModel):
    title: str
    objective: str = Field(validation_alias=AliasChoices("objective", "description"))
    parent_step_id: typing.Optional[int] = None
    position: typing.Optional[int] = None
    step_order: typing.Optional[int] = None
    insert_mode: InsertMode = "append_to_end"
    target_step_id: typing.Optional[int] = None
    depends_on_step_ids: list[int] = Field(default_factory=list)
    created_reason: typing.Optional[str] = None
    created_by_type: ExecutorType = "human"
    created_by_id: typing.Optional[str] = None
    executor_hint: typing.Optional[str] = None
    requires_approval: bool = True
    max_attempts: typing.Optional[int] = None
    estimate_category: typing.Optional[str] = None


class StepPatchRequest(BaseModel):
    title: typing.Optional[str] = None
    objective: typing.Optional[str] = Field(default=None, validation_alias=AliasChoices("objective", "description"))
    step_order: typing.Optional[int] = None
    depends_on_step_ids: typing.Optional[list[int]] = None
    executor_hint: typing.Optional[str] = None
    requires_approval: typing.Optional[bool] = None
    max_attempts: typing.Optional[int] = None
    estimate_category: typing.Optional[str] = None


class StepSkipRequest(BaseModel):
    reason: typing.Optional[str] = None
    actor_id: typing.Optional[str] = None


class SupersedeStepCreate(BaseModel):
    title: str
    objective: str = Field(validation_alias=AliasChoices("objective", "description"))
    depends_on_step_ids: typing.Optional[list[int]] = None
    executor_hint: typing.Optional[str] = None
    requires_approval: bool = True
    max_attempts: typing.Optional[int] = None
    estimate_category: typing.Optional[str] = None


class StepSupersedeRequest(BaseModel):
    new_step: SupersedeStepCreate
    reason: typing.Optional[str] = None
    actor_id: typing.Optional[str] = None


class StepForkRequest(BaseModel):
    variant_label: str
    title: str
    objective: str = Field(validation_alias=AliasChoices("objective", "description"))
    fork_reason: typing.Optional[str] = None
    clone_subtree: bool = False
    forked_from_run_id: typing.Optional[int] = None
    created_by_type: ExecutorType = "human"
    created_by_id: typing.Optional[str] = None
    estimate_category: typing.Optional[str] = None


class StepVariantSelectRequest(BaseModel):
    selected_step_id: int
    note: typing.Optional[str] = None
    actor_id: typing.Optional[str] = None


class StepVariantAbandonRequest(BaseModel):
    reason: typing.Optional[str] = None
    actor_id: typing.Optional[str] = None


class StepVariantSummary(BaseModel):
    step_id: int
    variant_label: typing.Optional[str] = None
    status: str
    branch_status: typing.Optional[str] = None
    runs_count: int
    approved_run_id: typing.Optional[int] = None
    artifacts_count: int
    metrics: dict[str, int]


class StepComparisonGroupRead(BaseModel):
    comparison_group_id: int
    task_id: int
    base_step_id: typing.Optional[int] = None
    status: str
    selected_step_id: typing.Optional[int] = None
    resolved_at: typing.Optional[datetime] = None
    variants: list[StepVariantSummary]
    next_actions: list[NextAction] = Field(default_factory=list)


class StepForkResponse(BaseModel):
    comparison_group_id: int
    forked_step_id: int
    cloned_steps_count: int


class StepRerunBranchRequest(BaseModel):
    executor_type: ExecutorType
    executor_ref: typing.Optional[str] = Field(default=None, validation_alias=AliasChoices("executor_ref", "executor_id"))
    input: dict[str, Any] = Field(default_factory=dict)
    variant_label: typing.Optional[str] = None
    title: typing.Optional[str] = None
    objective: typing.Optional[str] = Field(default=None, validation_alias=AliasChoices("objective", "description"))
    change_request: typing.Optional[str] = None
    fork_reason: typing.Optional[str] = None
    created_by_type: ExecutorType = "human"
    created_by_id: typing.Optional[str] = None


class StepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    parent_step_id: typing.Optional[int] = None
    comparison_group_id: typing.Optional[int] = None
    approved_run_id: typing.Optional[int] = None
    estimate_category: typing.Optional[str] = None
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
    created_reason: typing.Optional[str] = None
    created_by_type: str
    created_by_id: typing.Optional[str] = None
    inserted_after_step_id: typing.Optional[int] = None
    supersedes_step_id: typing.Optional[int] = None
    superseded_by_step_id: typing.Optional[int] = None
    executor_hint: typing.Optional[str] = None
    requires_approval: bool
    max_attempts: typing.Optional[int] = None
    variant_label: typing.Optional[str] = None
    selected_variant: typing.Optional[bool] = None
    is_fork: bool
    forked_from_step_id: typing.Optional[int] = None
    forked_from_run_id: typing.Optional[int] = None
    fork_reason: typing.Optional[str] = None
    branch_status: typing.Optional[str] = None
    cloned_from_step_id: typing.Optional[int] = None
    clone_batch_id: typing.Optional[str] = None
    is_selected_variant: typing.Optional[bool] = None
    consumed_ms: int = 0
    created_at: datetime
    updated_at: datetime


class StepRunCreate(BaseModel):
    executor_type: ExecutorType
    executor_ref: typing.Optional[str] = Field(default=None, validation_alias=AliasChoices("executor_ref", "executor_id"))
    input: dict[str, Any] = Field(default_factory=dict)


class AutoRunRequest(BaseModel):
    executor_type: ExecutorType = "agent"
    executor_ref: typing.Optional[str] = None
    input: dict[str, Any] = Field(default_factory=dict)


class AutoRunResponse(BaseModel):
    task_id: int
    started: bool
    step_id: typing.Optional[int] = None
    run_id: typing.Optional[int] = None
    message: str


class StepRunSubmit(BaseModel):
    output: dict[str, Any] = Field(default_factory=dict)
    error: typing.Optional[str] = None


class StepRunReview(BaseModel):
    decision: ReviewDecision
    comment: typing.Optional[str] = Field(default=None, validation_alias=AliasChoices("comment", "note"))
    reviewed_by_type: ExecutorType = "human"
    reviewed_by_id: typing.Optional[str] = None


class StepRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    step_id: int
    attempt_number: int
    executor_type: str
    executor_ref: typing.Optional[str] = None
    status: str
    input: dict[str, Any]
    output: typing.Optional[dict[str, Any]] = None
    error: typing.Optional[str] = None
    started_at: typing.Optional[datetime] = None
    submitted_at: typing.Optional[datetime] = None
    ended_at: typing.Optional[datetime] = None
    duration_ms: typing.Optional[int] = None
    created_at: datetime
    updated_at: datetime


class StepRerunBranchResponse(BaseModel):
    comparison_group_id: typing.Optional[int] = None
    forked_step_id: int
    cloned_steps_count: int


class ProgressReviewCreate(BaseModel):
    expected_progress_percent: float = Field(ge=0, le=100)
    created_by_type: ExecutorType = "human"
    created_by_id: typing.Optional[str] = None


class ProgressReviewDecisionCreate(BaseModel):
    decision: ProgressReviewDecision
    note: typing.Optional[str] = None
    decided_by_type: ExecutorType = "human"
    decided_by_id: typing.Optional[str] = None


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
    target_step_id: typing.Optional[int] = None


class ProgressReviewSuggestion(BaseModel):
    action_type: str
    message: str
    target_step_id: typing.Optional[int] = None
    api_path: typing.Optional[str] = None


class ProgressReviewRead(BaseModel):
    id: int
    task_id: int
    previous_review_id: typing.Optional[int] = None
    expected_progress_percent: float
    actual_progress_percent: float
    variance_percentage_points: float
    classification: ProgressReviewClassification
    snapshot: ProgressReviewSnapshot
    observations: list[ProgressReviewObservation]
    suggestions: list[ProgressReviewSuggestion]
    decision: typing.Optional[ProgressReviewDecision] = None
    decision_note: typing.Optional[str] = None
    decided_by_type: typing.Optional[str] = None
    decided_by_id: typing.Optional[str] = None
    decided_at: typing.Optional[datetime] = None
    created_by_type: str
    created_by_id: typing.Optional[str] = None
    created_at: datetime


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    step_id: typing.Optional[int] = None
    run_id: typing.Optional[int] = None
    decision: str
    comment: typing.Optional[str] = None
    reviewed_by_type: str
    reviewed_by_id: typing.Optional[str] = None
    created_at: datetime


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    step_id: typing.Optional[int] = None
    run_id: typing.Optional[int] = None
    capability_invocation_id: typing.Optional[int] = None
    type: str
    name: str
    uri: typing.Optional[str] = None
    metadata: dict[str, Any]
    created_at: datetime


class ArtifactCreate(BaseModel):
    type: str
    name: str
    uri: typing.Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodexRunCallback(BaseModel):
    task_id: int
    step_id: int
    run_id: int
    attempt_number: int
    status: Literal["completed", "failed"]
    summary: typing.Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactCreate] = Field(default_factory=list)
    error: typing.Optional[str] = None


class CodexTaskHookCallback(BaseModel):
    task_id: int
    status: Literal["completed", "failed"]
    summary: typing.Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactCreate] = Field(default_factory=list)
    error: typing.Optional[str] = None


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
    invoked_by_id: typing.Optional[str] = None
    capability_id: str
    input: dict[str, Any] = Field(default_factory=dict)


class CapabilityInvocationUpdate(BaseModel):
    status: CapabilityInvocationStatus
    output: typing.Optional[dict[str, Any]] = None
    error: typing.Optional[str] = None
    duration_ms: typing.Optional[int] = None
    artifacts: list[ArtifactCreate] = Field(default_factory=list)


class CapabilityInvocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    step_id: typing.Optional[int] = None
    run_id: typing.Optional[int] = None
    invoked_by_type: str
    invoked_by_id: typing.Optional[str] = None
    capability_id: str
    capability_name: typing.Optional[str] = None
    adapter_id: typing.Optional[str] = None
    handler_name: typing.Optional[str] = None
    status: str
    input: typing.Optional[dict[str, Any]] = None
    output: typing.Optional[dict[str, Any]] = None
    error: typing.Optional[str] = None
    duration_ms: typing.Optional[int] = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    completed_at: typing.Optional[datetime] = None
    ended_at: typing.Optional[datetime] = None


class CapabilityInvocationSummary(BaseModel):
    id: int
    step_id: typing.Optional[int] = None
    run_id: typing.Optional[int] = None
    capability_id: str
    capability_name: typing.Optional[str] = None
    status: str
    created_at: datetime
    completed_at: typing.Optional[datetime] = None


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    step_id: typing.Optional[int] = None
    run_id: typing.Optional[int] = None
    capability_invocation_id: typing.Optional[int] = None
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class TaskLogEntry(BaseModel):
    id: str
    timestamp: typing.Optional[datetime] = None
    scope: str
    event_type: str
    title: str
    message: typing.Optional[str] = None
    task_id: int
    step_id: typing.Optional[int] = None
    run_id: typing.Optional[int] = None
    capability_invocation_id: typing.Optional[int] = None
    artifact_id: typing.Optional[int] = None
    status: typing.Optional[str] = None
    duration_ms: typing.Optional[int] = None
    input: typing.Optional[dict[str, Any]] = None
    output: typing.Optional[dict[str, Any]] = None
    error: typing.Optional[str] = None
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
    description: typing.Optional[str] = None
    node_type: WbsNodeType = "work"
    position: int = Field(default=1, ge=1)
    parent_id: typing.Optional[int] = None
    execution_task_id: typing.Optional[int] = None
    created_by_id: typing.Optional[str] = None


class PlanningResourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    weekly_capacity_hours: typing.Optional[Decimal] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_capacity(self) -> "PlanningResourceCreate":
        if self.weekly_capacity_hours is not None and not self.weekly_capacity_hours.is_finite():
            raise ValueError("weekly capacity must be finite")
        return self


class PlanningResourceRead(BaseModel):
    id: int
    name: str
    weekly_capacity_hours: typing.Optional[Decimal] = None


class ResourceSkillUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    proficiency: int = Field(ge=1, le=5)


class ResourceWeekCapacityUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: date
    capacity_hours: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_week(self) -> "ResourceWeekCapacityUpsert":
        if self.week_start.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        if not self.capacity_hours.is_finite():
            raise ValueError("capacity must be finite")
        return self


class WbsSkillRequirementUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    minimum_proficiency: int = Field(ge=1, le=5)


class WbsWeekAllocationUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: int
    week_start: date
    planned_hours: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_week(self) -> "WbsWeekAllocationUpsert":
        if self.week_start.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        if not self.planned_hours.is_finite():
            raise ValueError("planned hours must be finite")
        return self


class ResourceCapacityRead(BaseModel):
    resource_id: int
    resource_name: str
    available_hours: typing.Optional[Decimal] = None
    planned_hours: Decimal
    root_planned_hours: Decimal
    other_root_planned_hours: Decimal
    utilization_percent: typing.Optional[Decimal] = None
    status: Literal["within_capacity", "over_capacity", "zero_capacity", "unknown_capacity"]


class CapacityNodeRead(BaseModel):
    node_id: int
    title: str
    planned_hours: Decimal
    resource_ids: list[int] = Field(default_factory=list)
    skill_status: Literal["met", "gap", "unknown", "not_required"]
    reasons: list[str] = Field(default_factory=list)


class CapacityWarningRead(BaseModel):
    code: str
    message: str
    resource_id: typing.Optional[int] = None
    node_id: typing.Optional[int] = None


class CapacitySuggestionRead(BaseModel):
    node_id: int
    resource_id: int
    resource_name: str
    message: str


class ResourceCapacityReport(BaseModel):
    root_id: int
    wbs_version: int
    week_start: date
    resources: list[ResourceCapacityRead] = Field(default_factory=list)
    nodes: list[CapacityNodeRead] = Field(default_factory=list)
    warnings: list[CapacityWarningRead] = Field(default_factory=list)
    suggestions: list[CapacitySuggestionRead] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class WbsNodeRead(BaseModel):
    id: int
    root_id: int
    parent_id: typing.Optional[int] = None
    execution_task_id: typing.Optional[int] = None
    node_type: WbsNodeType
    title: str
    description: typing.Optional[str] = None
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
    exclusion_reason: typing.Optional[str] = None


class WbsMilestoneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    criteria: str = Field(min_length=1)
    created_by_id: typing.Optional[str] = None


class WbsMilestonePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: typing.Optional[str] = Field(default=None, min_length=1, max_length=255)
    criteria: typing.Optional[str] = Field(default=None, min_length=1)


class WbsMilestoneRead(BaseModel):
    id: int
    node_id: int
    title: str
    criteria: str
    status: WbsMilestoneStatus
    completed_at: typing.Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class WbsDependencyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predecessor_id: int
    successor_id: int
    reason: typing.Optional[str] = None
    created_by_id: typing.Optional[str] = None


class WbsDependencyRead(BaseModel):
    id: int
    predecessor_id: int
    successor_id: int
    reason: typing.Optional[str] = None
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
    parent_id: typing.Optional[int] = None
    execution_task_id: typing.Optional[int] = None
    node_type: WbsNodeType
    title: str = Field(min_length=1, max_length=255)
    description: typing.Optional[str] = None
    position: int = Field(ge=1)
    is_active: bool = True


class WbsDependencyChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predecessor_id: int
    successor_id: int
    reason: typing.Optional[str] = None


class WbsChangeSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[WbsNodeChange]
    dependencies: list[WbsDependencyChange] = Field(default_factory=list)


class WbsChangeProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["update_nodes", "archive_nodes", "add_child", "add_dependency"] = "update_nodes"
    after: WbsChangeSnapshot
    reason: typing.Optional[str] = None
    created_by_id: typing.Optional[str] = None


class WbsChangeProposalDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: WbsProposalDecision
    note: typing.Optional[str] = None
    decided_by_id: typing.Optional[str] = None


class WbsChangeProposalRead(BaseModel):
    id: int
    root_id: int
    base_version: int
    operation: str
    reason: typing.Optional[str] = None
    before: WbsChangeSnapshot
    after: WbsChangeSnapshot
    status: WbsProposalStatus
    decided_by_id: typing.Optional[str] = None
    decision_note: typing.Optional[str] = None
    decided_at: typing.Optional[datetime] = None
    created_by_id: typing.Optional[str] = None
    created_at: datetime


EstimateSource = Literal["manual", "historical", "unavailable"]
EstimateAvailability = Literal["available", "unavailable"]
BufferStatus = Literal["unavailable", "not_applicable", "unused", "within_buffer", "exceeded"]


class ManualThreePointHours(BaseModel):
    model_config = ConfigDict(extra="forbid")

    optimistic: Decimal
    most_likely: Decimal
    pessimistic: Decimal

    @model_validator(mode="after")
    def validate_hours(self) -> "ManualThreePointHours":
        values = (self.optimistic, self.most_likely, self.pessimistic)
        if any(not value.is_finite() or value < 0 for value in values):
            raise ValueError("estimate hours must be finite and nonnegative")
        if not self.optimistic <= self.most_likely <= self.pessimistic:
            raise ValueError("estimate hours must satisfy optimistic <= most_likely <= pessimistic")
        return self


class WbsEstimateRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: int = Field(ge=0)
    estimate_category: typing.Optional[str] = None
    manual_estimate: typing.Optional[ManualThreePointHours] = None
    reason: typing.Optional[str] = None
    created_by_id: typing.Optional[str] = None


class WbsEstimateRevisionRead(BaseModel):
    id: int
    node_id: int
    revision_number: int
    estimate_category: typing.Optional[str] = None
    optimistic_ms: typing.Optional[int] = None
    most_likely_ms: typing.Optional[int] = None
    pessimistic_ms: typing.Optional[int] = None
    reason: typing.Optional[str] = None
    created_by_id: typing.Optional[str] = None
    created_at: datetime


class EstimateEvidenceRead(BaseModel):
    task_id: int
    step_id: int
    run_id: int
    duration_ms: int
    duration_source: Literal["stored", "submitted_at", "ended_at"]


class WbsNodeEstimateRead(BaseModel):
    node_id: int
    title: str
    atomic_work: bool
    source: EstimateSource
    availability: EstimateAvailability
    reason: typing.Optional[str] = None
    latest_revision: int
    estimate_category: typing.Optional[str] = None
    optimistic_ms: typing.Optional[int] = None
    most_likely_ms: typing.Optional[int] = None
    expected_ms: typing.Optional[int] = None
    conservative_ms: typing.Optional[int] = None
    safety_ms: typing.Optional[int] = None
    sample_count: int = 0
    evidence: list[EstimateEvidenceRead] = Field(default_factory=list)
    actual_ms: typing.Optional[int] = None
    actual_availability: EstimateAvailability
    actual_reason: typing.Optional[str] = None
    actual_excluded_step_ids: list[int] = Field(default_factory=list)


class WeightedScheduleRead(BaseModel):
    availability: EstimateAvailability
    reason: typing.Optional[str] = None
    node_ids: list[int] = Field(default_factory=list)
    covered_node_ids: list[int] = Field(default_factory=list)
    expected_ms: typing.Optional[int] = None
    conservative_ms: typing.Optional[int] = None
    candidate_count: int = 0
    unestimated_node_ids: list[int] = Field(default_factory=list)
    tie_break: str = "duration_then_depth_first_rank"


class BufferRead(BaseModel):
    availability: EstimateAvailability
    status: BufferStatus
    formula: str = "sqrt(sum((conservative_ms - expected_ms)^2))"
    recommended_ms: typing.Optional[int] = None
    consumed_ms: typing.Optional[int] = None
    remaining_ms: typing.Optional[int] = None
    consumption_percent: typing.Optional[float] = None
    covered_node_ids: list[int] = Field(default_factory=list)
    completed_node_ids: list[int] = Field(default_factory=list)
    excluded_node_ids: list[int] = Field(default_factory=list)
    exclusion_reasons: list[str] = Field(default_factory=list)
    zero_buffer_reason: typing.Optional[str] = None


class FeedingBufferRead(BufferRead):
    path_node_ids: list[int] = Field(default_factory=list)
    join_node_id: typing.Optional[int] = None


class EstimateBufferRead(BaseModel):
    availability: EstimateAvailability
    reason: typing.Optional[str] = None
    task_id: int
    root_id: typing.Optional[int] = None
    wbs_version: typing.Optional[int] = None
    node_estimates: list[WbsNodeEstimateRead] = Field(default_factory=list)
    schedule: WeightedScheduleRead
    project_buffer: BufferRead
    feeding_buffers: list[FeedingBufferRead] = Field(default_factory=list)
    actual_semantics: str = "sum_final_accepted_approved_runs_for_active_mainline_steps"
    assumptions: list[str] = Field(default_factory=list)
