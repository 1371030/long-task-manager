from __future__ import annotations

import math
import unicodedata
from collections import defaultdict, deque
from decimal import Decimal, ROUND_HALF_UP, localcontext

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from . import task_service, wbs_service
from .progress_service import duration_ms_between, progress_eligible_steps

HOUR_MS = Decimal(3_600_000)
MAX_SQLITE_INTEGER = 2**63 - 1
MIN_HISTORY_SAMPLES = 3
BUFFER_FORMULA = "sqrt(sum((conservative_ms - expected_ms)^2))"
ACTUAL_SEMANTICS = "sum_final_accepted_approved_runs_for_active_mainline_steps"


def normalize_estimate_category(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "-".join(unicodedata.normalize("NFKC", value).strip().casefold().split())
    if not normalized:
        raise HTTPException(status_code=422, detail="estimate_category cannot be blank")
    if len(normalized) > 64:
        raise HTTPException(status_code=422, detail="estimate_category must be at most 64 characters after normalization")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise HTTPException(status_code=422, detail="estimate_category cannot contain control characters")
    return normalized


def hours_to_ms(hours: Decimal) -> int:
    value = (hours * HOUR_MS).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if value > MAX_SQLITE_INTEGER:
        raise HTTPException(status_code=422, detail="estimate hours exceed the supported duration")
    return int(value)


def latest_revision(db: Session, node_id: int) -> models.WbsEstimateRevision | None:
    return (
        db.query(models.WbsEstimateRevision)
        .filter(models.WbsEstimateRevision.node_id == node_id)
        .order_by(models.WbsEstimateRevision.revision_number.desc(), models.WbsEstimateRevision.id.desc())
        .first()
    )


def revision_read(revision: models.WbsEstimateRevision) -> schemas.WbsEstimateRevisionRead:
    return schemas.WbsEstimateRevisionRead.model_validate(revision, from_attributes=True)


def create_estimate_revision(
    db: Session,
    node_id: int,
    payload: schemas.WbsEstimateRevisionCreate,
) -> schemas.WbsEstimateRevisionRead:
    node = wbs_service.get_node_or_404(db, node_id)
    current = latest_revision(db, node.id)
    current_number = current.revision_number if current is not None else 0
    if payload.base_revision != current_number:
        raise HTTPException(status_code=409, detail="Estimate revision is stale")

    category = normalize_estimate_category(payload.estimate_category)
    optimistic_ms = most_likely_ms = pessimistic_ms = None
    if payload.manual_estimate is not None:
        optimistic_ms = hours_to_ms(payload.manual_estimate.optimistic)
        most_likely_ms = hours_to_ms(payload.manual_estimate.most_likely)
        pessimistic_ms = hours_to_ms(payload.manual_estimate.pessimistic)

    revision = models.WbsEstimateRevision(
        node_id=node.id,
        revision_number=current_number + 1,
        estimate_category=category,
        optimistic_ms=optimistic_ms,
        most_likely_ms=most_likely_ms,
        pessimistic_ms=pessimistic_ms,
        reason=payload.reason,
        created_by_id=payload.created_by_id,
    )
    db.add(revision)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Estimate revision is stale") from exc
    root_id = wbs_service.root_id_for(node)
    before = None
    if current is not None:
        before = {
            "revision_number": current.revision_number,
            "estimate_category": current.estimate_category,
            "optimistic_ms": current.optimistic_ms,
            "most_likely_ms": current.most_likely_ms,
            "pessimistic_ms": current.pessimistic_ms,
        }
    after = {
        "revision_number": revision.revision_number,
        "estimate_category": revision.estimate_category,
        "optimistic_ms": revision.optimistic_ms,
        "most_likely_ms": revision.most_likely_ms,
        "pessimistic_ms": revision.pessimistic_ms,
    }
    wbs_service.commit_with_event(
        db,
        root_id,
        "wbs_estimate_revision_created",
        {
            "node_id": node.id,
            "before": before,
            "after": after,
            "reason": payload.reason,
            "actor_id": payload.created_by_id,
        },
    )
    db.refresh(revision)
    return revision_read(revision)


def resolved_run_duration(run: models.StepRun) -> tuple[int, str] | None:
    if run.duration_ms is not None:
        return max(run.duration_ms, 0), "stored"
    if run.started_at is None:
        return None
    if run.submitted_at is not None:
        return duration_ms_between(run.started_at, run.submitted_at), "submitted_at"
    if run.ended_at is not None:
        return duration_ms_between(run.started_at, run.ended_at), "ended_at"
    return None


def historical_evidence(
    db: Session,
    category: str,
    excluded_task_id: int | None,
) -> list[schemas.EstimateEvidenceRead]:
    query = (
        db.query(models.StepRun, models.Step)
        .join(models.Step, models.Step.id == models.StepRun.step_id)
        .filter(
            models.StepRun.status == "accepted",
            models.Step.estimate_category == category,
        )
    )
    if excluded_task_id is not None:
        query = query.filter(models.StepRun.task_id != excluded_task_id)
    evidence: list[schemas.EstimateEvidenceRead] = []
    for run, step in query.order_by(models.StepRun.id).all():
        resolved = resolved_run_duration(run)
        if resolved is None:
            continue
        duration_ms, duration_source = resolved
        evidence.append(
            schemas.EstimateEvidenceRead(
                task_id=run.task_id,
                step_id=step.id,
                run_id=run.id,
                duration_ms=duration_ms,
                duration_source=duration_source,
            )
        )
    return sorted(evidence, key=lambda item: (item.duration_ms, item.run_id))


def nearest_rank(values: list[int], percentile: Decimal) -> int:
    rank = math.ceil(float(percentile * len(values)))
    return values[max(rank - 1, 0)]


def median_half_up(values: list[int]) -> int:
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return int((Decimal(values[middle - 1] + values[middle]) / 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pert_expected_ms(optimistic_ms: int, most_likely_ms: int, pessimistic_ms: int) -> int:
    return int(
        (Decimal(optimistic_ms + 4 * most_likely_ms + pessimistic_ms) / 6).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def completed_node_actual(db: Session, task_id: int) -> tuple[int | None, str | None, list[int]]:
    steps = progress_eligible_steps(db, task_id)
    groups = {
        group.id: group
        for group in db.query(models.StepComparisonGroup)
        .filter(models.StepComparisonGroup.task_id == task_id)
        .all()
    }
    included: list[models.Step] = []
    excluded: list[int] = []
    for step in steps:
        if step.comparison_group_id is not None:
            group = groups.get(step.comparison_group_id)
            status = (group.status or group.selection_status) if group is not None else None
            if group is None or status in {"open", "comparing"} or group.selected_step_id != step.id:
                excluded.append(step.id)
                continue
        if step.status == "skipped":
            excluded.append(step.id)
            continue
        included.append(step)

    total = 0
    for step in included:
        if step.approved_run_id is None:
            return None, "missing_approved_run", sorted({*excluded, step.id})
        run = db.get(models.StepRun, step.approved_run_id)
        if run is None or run.task_id != task_id or run.step_id != step.id or run.status != "accepted":
            return None, "invalid_approved_run", sorted({*excluded, step.id})
        resolved = resolved_run_duration(run)
        if resolved is None:
            return None, "missing_approved_run_duration", sorted({*excluded, step.id})
        total += resolved[0]
    return total, None, sorted(excluded)


def node_estimate(
    db: Session,
    node: models.WbsNode,
    atomic_work: bool,
    completed: bool,
) -> schemas.WbsNodeEstimateRead:
    revision = latest_revision(db, node.id)
    revision_number = revision.revision_number if revision is not None else 0
    category = revision.estimate_category if revision is not None else None
    evidence: list[schemas.EstimateEvidenceRead] = []
    source: schemas.EstimateSource = "unavailable"
    availability: schemas.EstimateAvailability = "unavailable"
    reason: str | None = "not_atomic_work" if not atomic_work else None
    optimistic_ms = most_likely_ms = expected_ms = conservative_ms = safety_ms = None

    if atomic_work and revision is not None and revision.optimistic_ms is not None:
        source = "manual"
        availability = "available"
        optimistic_ms = revision.optimistic_ms
        most_likely_ms = revision.most_likely_ms
        conservative_ms = revision.pessimistic_ms
        expected_ms = pert_expected_ms(optimistic_ms, most_likely_ms, conservative_ms)
        safety_ms = max(conservative_ms - expected_ms, 0)
    elif atomic_work and category is None:
        reason = "missing_category"
    elif atomic_work:
        evidence = historical_evidence(db, category, node.execution_task_id)
        if len(evidence) < MIN_HISTORY_SAMPLES:
            reason = "no_history" if not evidence else "insufficient_history"
        else:
            values = [item.duration_ms for item in evidence]
            source = "historical"
            availability = "available"
            optimistic_ms = nearest_rank(values, Decimal("0.20"))
            expected_ms = median_half_up(values)
            conservative_ms = nearest_rank(values, Decimal("0.80"))
            most_likely_ms = expected_ms
            safety_ms = max(conservative_ms - expected_ms, 0)

    actual_ms = None
    actual_reason = "not_completed" if not completed else None
    actual_availability: schemas.EstimateAvailability = "unavailable"
    actual_excluded_step_ids: list[int] = []
    if completed and atomic_work:
        if node.execution_task_id is None:
            actual_reason = "missing_execution_task"
        else:
            actual_ms, actual_reason, actual_excluded_step_ids = completed_node_actual(db, node.execution_task_id)
            if actual_ms is not None:
                actual_availability = "available"
    elif completed:
        actual_reason = "not_atomic_work"

    return schemas.WbsNodeEstimateRead(
        node_id=node.id,
        title=node.title,
        atomic_work=atomic_work,
        source=source,
        availability=availability,
        reason=reason,
        latest_revision=revision_number,
        estimate_category=category,
        optimistic_ms=optimistic_ms,
        most_likely_ms=most_likely_ms,
        expected_ms=expected_ms,
        conservative_ms=conservative_ms,
        safety_ms=safety_ms,
        sample_count=len(evidence),
        evidence=evidence,
        actual_ms=actual_ms,
        actual_availability=actual_availability,
        actual_reason=actual_reason,
        actual_excluded_step_ids=actual_excluded_step_ids,
    )


def better_path(
    candidate_duration: int,
    candidate_path: list[int],
    current_duration: int | None,
    current_path: list[int],
    ranks: dict[int, int],
) -> bool:
    if current_duration is None or candidate_duration != current_duration:
        return current_duration is None or candidate_duration > current_duration
    candidate_key = tuple((ranks[node_id], node_id) for node_id in candidate_path)
    current_key = tuple((ranks[node_id], node_id) for node_id in current_path)
    return candidate_key < current_key


def longest_path(
    node_ids: set[int],
    edges: list[tuple[int, int]],
    weights: dict[int, int],
    ranks: dict[int, int],
    allowed_ends: set[int] | None = None,
) -> tuple[list[int], int, int]:
    if not node_ids:
        return [], 0, 0
    sort_keys = {node_id: (ranks[node_id], node_id) for node_id in node_ids}
    ordered = wbs_service.topological_order(node_ids, edges, sort_keys)
    predecessors: dict[int, list[int]] = defaultdict(list)
    successors: dict[int, list[int]] = defaultdict(list)
    for predecessor_id, successor_id in edges:
        predecessors[successor_id].append(predecessor_id)
        successors[predecessor_id].append(successor_id)
    durations: dict[int, int] = {}
    paths: dict[int, list[int]] = {}
    for node_id in ordered:
        duration = weights[node_id]
        path = [node_id]
        for predecessor_id in predecessors[node_id]:
            candidate_duration = durations[predecessor_id] + weights[node_id]
            candidate_path = [*paths[predecessor_id], node_id]
            if better_path(candidate_duration, candidate_path, duration, path, ranks):
                duration = candidate_duration
                path = candidate_path
        durations[node_id] = duration
        paths[node_id] = path
    ends = allowed_ends or {node_id for node_id in node_ids if not successors[node_id]}
    best_path: list[int] = []
    best_duration: int | None = None
    for node_id in sorted(ends, key=lambda item: (ranks[item], item)):
        if better_path(durations[node_id], paths[node_id], best_duration, best_path, ranks):
            best_duration = durations[node_id]
            best_path = paths[node_id]
    return best_path, best_duration or 0, len(ends)


def rss_ms(safety_values: list[int]) -> int:
    total = sum(value * value for value in safety_values)
    with localcontext() as context:
        context.prec = 50
        return int(Decimal(total).sqrt().quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def buffer_read(
    covered_node_ids: list[int],
    estimates: dict[int, schemas.WbsNodeEstimateRead],
) -> schemas.BufferRead:
    recommended_ms = rss_ms([estimates[node_id].safety_ms or 0 for node_id in covered_node_ids])
    consumed_ms = 0
    completed: list[int] = []
    excluded: list[int] = []
    reasons: list[str] = []
    for node_id in covered_node_ids:
        estimate = estimates[node_id]
        if estimate.actual_availability == "available" and estimate.actual_ms is not None:
            completed.append(node_id)
            consumed_ms += max(estimate.actual_ms - (estimate.expected_ms or 0), 0)
        else:
            excluded.append(node_id)
            if estimate.actual_reason not in {None, "not_completed"}:
                reasons.append(f"node_{node_id}:{estimate.actual_reason}")
    percentage = None
    zero_reason = None
    if recommended_ms == 0:
        status = "exceeded" if consumed_ms > 0 else "not_applicable"
        zero_reason = "all_covered_nodes_have_zero_safety"
    else:
        percentage = (Decimal(consumed_ms) * 100 / Decimal(recommended_ms)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if consumed_ms == 0:
            status = "unused"
        elif percentage <= 100:
            status = "within_buffer"
        else:
            status = "exceeded"
    return schemas.BufferRead(
        availability="available",
        status=status,
        recommended_ms=recommended_ms,
        consumed_ms=consumed_ms,
        remaining_ms=max(recommended_ms - consumed_ms, 0),
        consumption_percent=float(percentage) if percentage is not None else None,
        covered_node_ids=covered_node_ids,
        completed_node_ids=completed,
        excluded_node_ids=excluded,
        exclusion_reasons=sorted(set(reasons)),
        zero_buffer_reason=zero_reason,
    )


def unavailable_buffer(reason: str, node_ids: list[int] | None = None) -> schemas.BufferRead:
    return schemas.BufferRead(
        availability="unavailable",
        status="unavailable",
        covered_node_ids=node_ids or [],
        excluded_node_ids=node_ids or [],
        exclusion_reasons=[reason],
    )


def weak_components(node_ids: set[int], edges: list[tuple[int, int]], ranks: dict[int, int]) -> list[set[int]]:
    neighbors: dict[int, set[int]] = defaultdict(set)
    for predecessor_id, successor_id in edges:
        neighbors[predecessor_id].add(successor_id)
        neighbors[successor_id].add(predecessor_id)
    remaining = set(node_ids)
    components: list[set[int]] = []
    while remaining:
        start = min(remaining, key=lambda item: (ranks[item], item))
        component: set[int] = set()
        queue = deque([start])
        while queue:
            current = queue.popleft()
            if current not in remaining:
                continue
            remaining.remove(current)
            component.add(current)
            queue.extend(sorted(neighbors[current] & remaining, key=lambda item: (ranks[item], item)))
        components.append(component)
    return components


def feeding_buffers(
    active_ids: set[int],
    edges: list[tuple[int, int]],
    main_path: list[int],
    weights: dict[int, int],
    ranks: dict[int, int],
    estimates: dict[int, schemas.WbsNodeEstimateRead],
) -> list[schemas.FeedingBufferRead]:
    main_set = set(main_path)
    off_main = active_ids - main_set
    off_edges = [(left, right) for left, right in edges if left in off_main and right in off_main]
    successors: dict[int, list[int]] = defaultdict(list)
    for left, right in edges:
        successors[left].append(right)
    main_index = {node_id: index for index, node_id in enumerate(main_path)}
    result: list[schemas.FeedingBufferRead] = []
    for component in weak_components(off_main, off_edges, ranks):
        reachable_main: set[int] = set()
        for start in component:
            queue = deque([start])
            seen = {start}
            while queue:
                current = queue.popleft()
                for successor in successors[current]:
                    if successor in main_set:
                        reachable_main.add(successor)
                    elif successor in component and successor not in seen:
                        seen.add(successor)
                        queue.append(successor)
        join_node_id = min(reachable_main, key=main_index.__getitem__) if reachable_main else None
        if join_node_id is None:
            end_ids = {
                node_id
                for node_id in component
                if not any(successor in component for successor in successors[node_id])
            }
        else:
            can_reach_join: set[int] = set()
            reverse: dict[int, list[int]] = defaultdict(list)
            direct_join: set[int] = set()
            for left, right in edges:
                if left in component and right in component:
                    reverse[right].append(left)
                elif left in component and right == join_node_id:
                    direct_join.add(left)
            queue = deque(direct_join)
            while queue:
                current = queue.popleft()
                if current in can_reach_join:
                    continue
                can_reach_join.add(current)
                queue.extend(reverse[current])
            end_ids = direct_join
            component = can_reach_join
        path, _, _ = longest_path(
            component,
            [(left, right) for left, right in off_edges if left in component and right in component],
            weights,
            ranks,
            end_ids,
        )
        covered = [node_id for node_id in path if estimates[node_id].atomic_work]
        if not covered:
            continue
        base = buffer_read(covered, estimates)
        buffer_data = base.model_dump()
        buffer_data["excluded_node_ids"] = sorted(
            (component - set(path)) | set(base.excluded_node_ids),
            key=lambda item: (ranks[item], item),
        )
        result.append(
            schemas.FeedingBufferRead(
                **buffer_data,
                path_node_ids=path,
                join_node_id=join_node_id,
            )
        )
    return result


def unavailable_response(task_id: int, reason: str) -> schemas.EstimateBufferRead:
    return schemas.EstimateBufferRead(
        availability="unavailable",
        reason=reason,
        task_id=task_id,
        schedule=schemas.WeightedScheduleRead(availability="unavailable", reason=reason),
        project_buffer=unavailable_buffer(reason),
        assumptions=[],
    )


def read_estimate_buffer(db: Session, task_id: int) -> schemas.EstimateBufferRead:
    task_service.get_task_or_404(db, task_id)
    linked_node = (
        db.query(models.WbsNode)
        .filter(models.WbsNode.execution_task_id == task_id)
        .order_by(models.WbsNode.id)
        .first()
    )
    if linked_node is None:
        return unavailable_response(task_id, "wbs_not_found")
    root_id = wbs_service.root_id_for(linked_node)
    root = wbs_service.get_root_or_404(db, root_id)
    nodes = wbs_service.tree_nodes(db, root_id)
    ordered = wbs_service.depth_first(nodes, root_id)
    rank = {node.id: index for index, (node, _) in enumerate(ordered)}
    children = wbs_service.children_by_parent(nodes)
    active_ids = {node.id for node in nodes if node.is_active}
    atomic_ids = {
        node.id
        for node in nodes
        if node.is_active
        and node.node_type == "work"
        and not any(child.is_active for child in children.get(node.id, []))
    }
    tree = wbs_service.read_tree(db, root_id)
    status_by_id = {node.id: node.status for node in tree.nodes}
    estimates_list = [
        node_estimate(db, node, node.id in atomic_ids, status_by_id[node.id] == "completed")
        for node, _ in ordered
    ]
    estimates = {item.node_id: item for item in estimates_list}
    dependencies = wbs_service.tree_dependencies(db, active_ids)
    edges = [(item.predecessor_id, item.successor_id) for item in dependencies]
    sort_keys = {node_id: (rank[node_id], node_id) for node_id in active_ids}
    wbs_service.topological_order(active_ids, edges, sort_keys)
    unestimated = sorted(
        (node_id for node_id in atomic_ids if estimates[node_id].availability == "unavailable"),
        key=lambda item: (rank[item], item),
    )
    assumptions = [
        "Only explicit WBS dependencies define precedence.",
        "Manual estimates override accepted-run history.",
        "Completed actuals use final accepted approved runs on active mainline steps.",
    ]
    if unestimated:
        reason = "unestimated_atomic_nodes"
        return schemas.EstimateBufferRead(
            availability="unavailable",
            reason=reason,
            task_id=task_id,
            root_id=root_id,
            wbs_version=root.version,
            node_estimates=estimates_list,
            schedule=schemas.WeightedScheduleRead(
                availability="unavailable",
                reason=reason,
                unestimated_node_ids=unestimated,
            ),
            project_buffer=unavailable_buffer(reason, unestimated),
            assumptions=assumptions,
        )

    weights = {node_id: estimates[node_id].expected_ms or 0 for node_id in active_ids}
    main_path, expected_ms, candidate_count = longest_path(active_ids, edges, weights, rank)
    covered = [node_id for node_id in main_path if node_id in atomic_ids]
    conservative_ms = sum(estimates[node_id].conservative_ms or 0 for node_id in covered)
    schedule = schemas.WeightedScheduleRead(
        availability="available",
        node_ids=main_path,
        covered_node_ids=covered,
        expected_ms=expected_ms,
        conservative_ms=conservative_ms,
        candidate_count=candidate_count,
    )
    return schemas.EstimateBufferRead(
        availability="available",
        task_id=task_id,
        root_id=root_id,
        wbs_version=root.version,
        node_estimates=estimates_list,
        schedule=schedule,
        project_buffer=buffer_read(covered, estimates),
        feeding_buffers=feeding_buffers(active_ids, edges, main_path, weights, rank, estimates),
        actual_semantics=ACTUAL_SEMANTICS,
        assumptions=assumptions,
    )
