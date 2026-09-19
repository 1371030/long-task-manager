from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from . import task_service
from .progress_service import compute_progress

EXCLUDED_TASK_STATUSES = {"archived", "cancelled"}


def get_node_or_404(db: Session, node_id: int) -> models.WbsNode:
    node = db.get(models.WbsNode, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="WBS node not found")
    return node


def get_root_or_404(db: Session, root_id: int) -> models.WbsNode:
    root = get_node_or_404(db, root_id)
    if root.parent_id is not None or root.root_id != root.id:
        raise HTTPException(status_code=404, detail="WBS root not found")
    return root


def root_id_for(node: models.WbsNode) -> int:
    return node.root_id or node.id


def tree_nodes(db: Session, root_id: int) -> list[models.WbsNode]:
    return (
        db.query(models.WbsNode)
        .filter((models.WbsNode.id == root_id) | (models.WbsNode.root_id == root_id))
        .order_by(models.WbsNode.position, models.WbsNode.id)
        .all()
    )


def tree_dependencies(db: Session, node_ids: set[int]) -> list[models.WbsDependency]:
    if not node_ids:
        return []
    return (
        db.query(models.WbsDependency)
        .filter(
            models.WbsDependency.predecessor_id.in_(node_ids),
            models.WbsDependency.successor_id.in_(node_ids),
        )
        .order_by(models.WbsDependency.predecessor_id, models.WbsDependency.successor_id, models.WbsDependency.id)
        .all()
    )


def children_by_parent(nodes: list[models.WbsNode]) -> dict[int | None, list[models.WbsNode]]:
    children: dict[int | None, list[models.WbsNode]] = defaultdict(list)
    for node in nodes:
        children[node.parent_id].append(node)
    for siblings in children.values():
        siblings.sort(key=lambda item: (item.position, item.id))
    return children


def depth_first(nodes: list[models.WbsNode], root_id: int) -> list[tuple[models.WbsNode, int]]:
    by_id = {node.id: node for node in nodes}
    if root_id not in by_id:
        raise HTTPException(status_code=404, detail="WBS root not found")
    children = children_by_parent(nodes)
    ordered: list[tuple[models.WbsNode, int]] = []
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(node: models.WbsNode, depth: int) -> None:
        if node.id in visiting:
            raise HTTPException(status_code=400, detail="WBS tree contains a cycle")
        if node.id in visited:
            return
        visiting.add(node.id)
        ordered.append((node, depth))
        for child in children.get(node.id, []):
            visit(child, depth + 1)
        visiting.remove(node.id)
        visited.add(node.id)

    visit(by_id[root_id], 0)
    if len(visited) != len(nodes):
        raise HTTPException(status_code=400, detail="WBS tree contains a disconnected node")
    return ordered


def topological_order(node_ids: set[int], edges: list[tuple[int, int]], sort_keys: dict[int, tuple[int, int]]) -> list[int]:
    successors: dict[int, list[int]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in node_ids}
    seen_edges: set[tuple[int, int]] = set()
    for predecessor_id, successor_id in edges:
        if predecessor_id == successor_id:
            raise HTTPException(status_code=400, detail="A WBS node cannot depend on itself")
        if predecessor_id not in node_ids or successor_id not in node_ids:
            raise HTTPException(status_code=400, detail="WBS dependency must use nodes from the same tree")
        edge = (predecessor_id, successor_id)
        if edge in seen_edges:
            raise HTTPException(status_code=400, detail="WBS dependency is duplicated")
        seen_edges.add(edge)
        successors[predecessor_id].append(successor_id)
        indegree[successor_id] += 1
    ready = sorted((node_id for node_id, count in indegree.items() if count == 0), key=sort_keys.__getitem__)
    ordered: list[int] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for successor_id in sorted(successors[current], key=sort_keys.__getitem__):
            indegree[successor_id] -= 1
            if indegree[successor_id] == 0:
                ready.append(successor_id)
                ready.sort(key=sort_keys.__getitem__)
    if len(ordered) != len(node_ids):
        raise HTTPException(status_code=400, detail="WBS dependencies contain a cycle")
    return ordered


def node_task_progress(db: Session, node: models.WbsNode) -> tuple[float, schemas.WbsNodeStatus, str | None]:
    if not node.is_active:
        return 0.0, "not_started", "Inactive WBS node is excluded"
    if node.execution_task_id is None:
        return 0.0, "not_started", "Node has no execution task"
    task = db.get(models.Task, node.execution_task_id)
    if task is None:
        return 0.0, "not_started", "Execution task not found"
    if task.status in EXCLUDED_TASK_STATUSES:
        return 0.0, "not_started", f"Task status {task.status} is excluded"
    if task.status == "completed":
        return 100.0, "completed", None
    progress = compute_progress(db, task.id).progress_percent
    if task.status == "blocked":
        return progress, "blocked", None
    return progress, "in_progress" if progress > 0 else "not_started", None


def milestone_read(milestone: models.Milestone, completed: bool = False) -> schemas.WbsMilestoneRead:
    return schemas.WbsMilestoneRead(
        id=milestone.id,
        node_id=milestone.node_id,
        title=milestone.title,
        criteria=milestone.criteria,
        status="completed" if completed else "open",
        completed_at=milestone.completed_at if completed else None,
        created_at=milestone.created_at,
        updated_at=milestone.updated_at,
    )


def critical_path(
    nodes: list[models.WbsNode],
    dependencies: list[models.WbsDependency],
    statuses: dict[int, schemas.WbsNodeStatus],
) -> schemas.WbsCriticalPathHint:
    unfinished = {node.id for node in nodes if node.is_active and statuses[node.id] != "completed"}
    sort_keys = {node.id: (node.position, node.id) for node in nodes}
    edges = [
        (dependency.predecessor_id, dependency.successor_id)
        for dependency in dependencies
        if dependency.predecessor_id in unfinished and dependency.successor_id in unfinished
    ]
    ordered = topological_order(unfinished, edges, sort_keys) if unfinished else []
    predecessors: dict[int, list[int]] = defaultdict(list)
    for predecessor_id, successor_id in edges:
        predecessors[successor_id].append(predecessor_id)
    best: dict[int, list[int]] = {}
    for node_id in ordered:
        candidates = [best[predecessor_id] for predecessor_id in predecessors[node_id]]
        prefix = max(candidates, key=lambda path: (len(path), tuple(-item for item in path)), default=[])
        best[node_id] = [*prefix, node_id]
    path = max(best.values(), key=lambda item: (len(item), tuple(-node_id for node_id in item)), default=[])
    return schemas.WbsCriticalPathHint(node_ids=path, length=len(path))


def read_tree(db: Session, root_id: int) -> schemas.WbsTreeRead:
    root = get_root_or_404(db, root_id)
    nodes = tree_nodes(db, root.id)
    ordered = depth_first(nodes, root.id)
    children = children_by_parent(nodes)
    node_ids = {node.id for node in nodes}
    dependencies = tree_dependencies(db, node_ids)
    sort_keys = {node.id: (node.position, node.id) for node in nodes}
    topological_order(node_ids, [(item.predecessor_id, item.successor_id) for item in dependencies], sort_keys)
    milestones = (
        db.query(models.Milestone)
        .filter(models.Milestone.node_id.in_(node_ids))
        .order_by(models.Milestone.node_id, models.Milestone.id)
        .all()
    )
    milestones_by_node: dict[int, list[models.Milestone]] = defaultdict(list)
    for milestone in milestones:
        milestones_by_node[milestone.node_id].append(milestone)

    statuses: dict[int, schemas.WbsNodeStatus] = {}
    progress_values: dict[int, float] = {}
    exclusions: dict[int, str | None] = {}
    for node, _ in reversed(ordered):
        active_children = [child for child in children.get(node.id, []) if child.is_active]
        if active_children:
            reportable = [child for child in active_children if exclusions[child.id] is None]
            if not reportable:
                progress, status, reason = 0.0, "not_started", "No active direct child has reportable progress"
            else:
                progress = round(sum(progress_values[child.id] for child in reportable) / len(reportable), 2)
                all_children_reportable = len(reportable) == len(active_children)
                status = "completed" if all_children_reportable and all(statuses[child.id] == "completed" for child in reportable) else ("in_progress" if progress > 0 else "not_started")
                reason = None
        else:
            progress, status, reason = node_task_progress(db, node)
        progress_values[node.id] = progress
        statuses[node.id] = status
        exclusions[node.id] = reason

    predecessor_map: dict[int, list[int]] = defaultdict(list)
    for dependency in dependencies:
        predecessor_map[dependency.successor_id].append(dependency.predecessor_id)
    for node, _ in ordered:
        if statuses[node.id] == "completed":
            continue
        if any(statuses[predecessor_id] != "completed" for predecessor_id in predecessor_map[node.id]):
            statuses[node.id] = "blocked"

    reads: list[schemas.WbsNodeRead] = []
    milestone_reads: list[schemas.WbsMilestoneRead] = []
    for node, depth in ordered:
        node_completed = statuses[node.id] == "completed"
        milestone_reads.extend(milestone_read(item, completed=node_completed) for item in milestones_by_node[node.id])
        blocked_by = [predecessor_id for predecessor_id in predecessor_map[node.id] if statuses[predecessor_id] != "completed"]
        reads.append(
            schemas.WbsNodeRead(
                id=node.id,
                root_id=root.id,
                parent_id=node.parent_id,
                execution_task_id=node.execution_task_id,
                node_type=node.node_type,
                title=node.title,
                description=node.description,
                position=node.position,
                depth=depth,
                is_active=node.is_active,
                version=node.version,
                status=statuses[node.id],
                progress_percent=progress_values[node.id],
                child_ids=[child.id for child in children.get(node.id, [])],
                milestone_ids=[item.id for item in milestones_by_node[node.id]],
                blocked_by_node_ids=blocked_by,
                excluded_from_rollup=exclusions[node.id] is not None,
                exclusion_reason=exclusions[node.id],
            )
        )

    active_root_children = [child for child in children.get(root.id, []) if child.is_active]
    rollup_nodes = active_root_children or [root]
    reportable = [node for node in rollup_nodes if exclusions[node.id] is None]
    excluded = [node for node in rollup_nodes if exclusions[node.id] is not None]
    rollup_progress = round(sum(progress_values[node.id] for node in reportable) / len(reportable), 2) if reportable else 0.0
    return schemas.WbsTreeRead(
        root_id=root.id,
        version=root.version,
        nodes=reads,
        milestones=milestone_reads,
        dependencies=[schemas.WbsDependencyRead.model_validate(item, from_attributes=True) for item in dependencies],
        rollup=schemas.WbsRollupSummary(
            progress_percent=rollup_progress,
            status=statuses[root.id],
            reportable_node_count=len(reportable),
            excluded_node_count=len(excluded),
            exclusion_reasons=sorted({exclusions[node.id] for node in excluded if exclusions[node.id]}),
        ),
        critical_path=critical_path(nodes, dependencies, statuses),
    )


def audit_task_id(db: Session, root_id: int) -> int:
    root = get_root_or_404(db, root_id)
    if root.execution_task_id is None:
        raise HTTPException(status_code=400, detail="WBS root has no execution task")
    return root.execution_task_id


def commit_with_event(db: Session, root_id: int, event_type: str, payload: dict[str, Any]) -> None:
    task_id = audit_task_id(db, root_id)
    task_service.record_event(db, task_id, event_type, payload)
    task_service.commit_and_write_task_log(db, task_id)


def create_root(db: Session, task_id: int, payload: schemas.WbsNodeCreate) -> schemas.WbsTreeRead:
    task_service.get_task_or_404(db, task_id)
    if payload.parent_id is not None:
        raise HTTPException(status_code=400, detail="A root WBS node cannot have a parent")
    if payload.execution_task_id not in (None, task_id):
        raise HTTPException(status_code=400, detail="Root execution_task_id must match the URL task")
    if db.query(models.WbsNode).filter(models.WbsNode.execution_task_id == task_id).first() is not None:
        raise HTTPException(status_code=409, detail="Task is already linked to a WBS node")
    node = models.WbsNode(
        title=payload.title,
        description=payload.description,
        node_type=payload.node_type,
        position=payload.position,
        execution_task_id=task_id,
        created_by_id=payload.created_by_id,
    )
    db.add(node)
    db.flush()
    node.root_id = node.id
    task_service.record_event(db, task_id, "wbs_node_created", {"node_id": node.id, "root_id": node.id})
    task_service.commit_and_write_task_log(db, task_id)
    return read_tree(db, node.id)


def read_task_tree(db: Session, task_id: int) -> schemas.WbsTreeRead:
    task_service.get_task_or_404(db, task_id)
    node = db.query(models.WbsNode).filter(models.WbsNode.execution_task_id == task_id).order_by(models.WbsNode.id).first()
    if node is None:
        raise HTTPException(status_code=404, detail="WBS tree not found")
    return read_tree(db, root_id_for(node))


def create_milestone(db: Session, node_id: int, payload: schemas.WbsMilestoneCreate) -> schemas.WbsMilestoneRead:
    node = get_node_or_404(db, node_id)
    milestone = models.Milestone(
        node_id=node.id,
        title=payload.title,
        criteria=payload.criteria,
        created_by_id=payload.created_by_id,
    )
    db.add(milestone)
    db.flush()
    root_id = root_id_for(node)
    commit_with_event(db, root_id, "wbs_milestone_created", {"node_id": node.id, "milestone_id": milestone.id})
    tree = read_tree(db, root_id)
    return next(item for item in tree.milestones if item.id == milestone.id)


def update_milestone(db: Session, milestone_id: int, payload: schemas.WbsMilestonePatch) -> schemas.WbsMilestoneRead:
    milestone = db.get(models.Milestone, milestone_id)
    if milestone is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    if payload.title is not None:
        milestone.title = payload.title
    if payload.criteria is not None:
        milestone.criteria = payload.criteria
    root_id = root_id_for(milestone.node)
    commit_with_event(db, root_id, "wbs_milestone_updated", {"node_id": milestone.node_id, "milestone_id": milestone.id})
    tree = read_tree(db, root_id)
    return next(item for item in tree.milestones if item.id == milestone.id)


def change_node(node: models.WbsNode) -> schemas.WbsNodeChange:
    return schemas.WbsNodeChange(
        id=node.id,
        parent_id=node.parent_id,
        execution_task_id=node.execution_task_id,
        node_type=node.node_type,
        title=node.title,
        description=node.description,
        position=node.position,
        is_active=node.is_active,
    )


def canonical_snapshot(db: Session, root_id: int) -> schemas.WbsChangeSnapshot:
    nodes = tree_nodes(db, root_id)
    dependencies = tree_dependencies(db, {node.id for node in nodes})
    return schemas.WbsChangeSnapshot(
        nodes=[change_node(node) for node, _ in depth_first(nodes, root_id)],
        dependencies=[
            schemas.WbsDependencyChange(
                predecessor_id=item.predecessor_id,
                successor_id=item.successor_id,
                reason=item.reason,
            )
            for item in dependencies
        ],
    )


def validate_snapshot(db: Session, root: models.WbsNode, snapshot: schemas.WbsChangeSnapshot) -> schemas.WbsChangeSnapshot:
    if not snapshot.nodes:
        raise HTTPException(status_code=400, detail="WBS snapshot must contain nodes")
    by_id = {node.id: node for node in snapshot.nodes}
    if len(by_id) != len(snapshot.nodes) or 0 in by_id:
        raise HTTPException(status_code=400, detail="WBS node IDs must be unique and non-zero")
    current_ids = {node.id for node in tree_nodes(db, root.id)}
    if not current_ids.issubset(by_id):
        raise HTTPException(status_code=400, detail="WBS nodes cannot be deleted; archive them instead")
    if root.id not in by_id or by_id[root.id].parent_id is not None:
        raise HTTPException(status_code=400, detail="WBS root must remain the only parentless existing node")
    if by_id[root.id].execution_task_id != root.execution_task_id:
        raise HTTPException(status_code=400, detail="WBS root execution task cannot change")
    for node in snapshot.nodes:
        if node.id < 0 and node.parent_id is None:
            raise HTTPException(status_code=400, detail="New WBS nodes require a parent")
        if node.id != root.id and node.parent_id not in by_id:
            raise HTTPException(status_code=400, detail="Every non-root WBS node requires a parent in the same tree")
    siblings: set[tuple[int | None, int]] = set()
    for node in snapshot.nodes:
        key = (node.parent_id, node.position)
        if key in siblings:
            raise HTTPException(status_code=400, detail="Sibling WBS positions must be unique")
        siblings.add(key)
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(node_id: int) -> None:
        if node_id in visiting:
            raise HTTPException(status_code=400, detail="WBS tree contains a cycle")
        if node_id in visited:
            return
        visiting.add(node_id)
        parent_id = by_id[node_id].parent_id
        if parent_id is not None:
            visit(parent_id)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in by_id:
        visit(node_id)
    task_ids = [node.execution_task_id for node in snapshot.nodes if node.execution_task_id is not None]
    if len(task_ids) != len(set(task_ids)):
        raise HTTPException(status_code=400, detail="An execution task can only be linked to one WBS node")
    for task_id in task_ids:
        task_service.get_task_or_404(db, task_id)
    external_link = (
        db.query(models.WbsNode)
        .filter(models.WbsNode.execution_task_id.in_(task_ids), ~models.WbsNode.id.in_(current_ids))
        .first()
        if task_ids
        else None
    )
    if external_link is not None:
        raise HTTPException(status_code=409, detail="Execution task is already linked to another WBS tree")
    sort_keys = {node.id: (node.position, node.id) for node in snapshot.nodes}
    topological_order(
        set(by_id),
        [(item.predecessor_id, item.successor_id) for item in snapshot.dependencies],
        sort_keys,
    )
    return schemas.WbsChangeSnapshot(
        nodes=sorted(snapshot.nodes, key=lambda item: (item.parent_id is not None, item.parent_id or 0, item.position, item.id)),
        dependencies=sorted(snapshot.dependencies, key=lambda item: (item.predecessor_id, item.successor_id)),
    )


def snapshot_json(snapshot: schemas.WbsChangeSnapshot) -> str:
    return task_service.encode_json(snapshot.model_dump(mode="json"))


def proposal_read(proposal: models.WbsChangeProposal) -> schemas.WbsChangeProposalRead:
    return schemas.WbsChangeProposalRead(
        id=proposal.id,
        root_id=proposal.root_id,
        base_version=proposal.base_version,
        operation=proposal.operation,
        reason=proposal.reason,
        before=schemas.WbsChangeSnapshot.model_validate(task_service.decode_json(proposal.before_json)),
        after=schemas.WbsChangeSnapshot.model_validate(task_service.decode_json(proposal.after_json)),
        status=proposal.status,
        decided_by_id=proposal.decided_by_id,
        decision_note=proposal.decision_note,
        decided_at=proposal.decided_at,
        created_by_id=proposal.created_by_id,
        created_at=proposal.created_at,
    )


def create_proposal(db: Session, root_id: int, payload: schemas.WbsChangeProposalCreate) -> schemas.WbsChangeProposalRead:
    root = get_root_or_404(db, root_id)
    before = canonical_snapshot(db, root.id)
    after = validate_snapshot(db, root, payload.after)
    proposal = models.WbsChangeProposal(
        root_id=root.id,
        base_version=root.version,
        operation=payload.operation,
        reason=payload.reason,
        before_json=snapshot_json(before),
        after_json=snapshot_json(after),
        created_by_id=payload.created_by_id,
    )
    db.add(proposal)
    db.flush()
    commit_with_event(
        db,
        root.id,
        "wbs_change_proposed",
        {"proposal_id": proposal.id, "root_id": root.id, "base_version": root.version, "operation": proposal.operation},
    )
    return proposal_read(proposal)


def propose_child(db: Session, parent_id: int, payload: schemas.WbsNodeCreate) -> schemas.WbsChangeProposalRead:
    parent = get_node_or_404(db, parent_id)
    if payload.parent_id not in (None, parent.id):
        raise HTTPException(status_code=400, detail="Child parent_id must match the URL node")
    root_id = root_id_for(parent)
    snapshot = canonical_snapshot(db, root_id)
    temporary_id = min([node.id for node in snapshot.nodes if node.id < 0], default=0) - 1
    snapshot.nodes.append(
        schemas.WbsNodeChange(
            id=temporary_id,
            parent_id=parent.id,
            execution_task_id=payload.execution_task_id,
            node_type=payload.node_type,
            title=payload.title,
            description=payload.description,
            position=payload.position,
        )
    )
    return create_proposal(
        db,
        root_id,
        schemas.WbsChangeProposalCreate(
            operation="add_child",
            after=snapshot,
            reason=f"Add child under WBS node {parent.id}",
            created_by_id=payload.created_by_id,
        ),
    )


def propose_dependency(db: Session, root_id: int, payload: schemas.WbsDependencyCreate) -> schemas.WbsChangeProposalRead:
    snapshot = canonical_snapshot(db, root_id)
    snapshot.dependencies.append(
        schemas.WbsDependencyChange(
            predecessor_id=payload.predecessor_id,
            successor_id=payload.successor_id,
            reason=payload.reason,
        )
    )
    return create_proposal(
        db,
        root_id,
        schemas.WbsChangeProposalCreate(
            operation="add_dependency",
            after=snapshot,
            reason=payload.reason or "Add WBS dependency",
            created_by_id=payload.created_by_id,
        ),
    )


def list_proposals(db: Session, root_id: int) -> list[schemas.WbsChangeProposalRead]:
    get_root_or_404(db, root_id)
    proposals = (
        db.query(models.WbsChangeProposal)
        .filter(models.WbsChangeProposal.root_id == root_id)
        .order_by(models.WbsChangeProposal.created_at.desc(), models.WbsChangeProposal.id.desc())
        .all()
    )
    return [proposal_read(proposal) for proposal in proposals]


def apply_snapshot(db: Session, root: models.WbsNode, snapshot: schemas.WbsChangeSnapshot, version: int) -> None:
    validated = validate_snapshot(db, root, snapshot)
    current = {node.id: node for node in tree_nodes(db, root.id)}
    id_map = {node_id: node_id for node_id in current}
    for node in current.values():
        node.execution_task_id = None
    db.flush()
    pending = [node for node in validated.nodes if node.id < 0]
    while pending:
        progressed = False
        for change in pending[:]:
            if change.parent_id not in id_map:
                continue
            node = models.WbsNode(
                root_id=root.id,
                parent_id=id_map[change.parent_id],
                execution_task_id=change.execution_task_id,
                node_type=change.node_type,
                title=change.title,
                description=change.description,
                position=change.position,
                is_active=change.is_active,
                version=version,
            )
            db.add(node)
            db.flush()
            id_map[change.id] = node.id
            current[node.id] = node
            pending.remove(change)
            progressed = True
        if not progressed:
            raise HTTPException(status_code=400, detail="WBS proposal contains unresolved parent references")
    for change in validated.nodes:
        if change.id < 0:
            continue
        node = current[change.id]
        node.parent_id = id_map[change.parent_id] if change.parent_id is not None else None
        node.execution_task_id = change.execution_task_id
        node.node_type = change.node_type
        node.title = change.title
        node.description = change.description
        node.position = change.position
        node.is_active = change.is_active
        node.version = version
    db.query(models.WbsDependency).filter(
        models.WbsDependency.predecessor_id.in_(set(current)),
        models.WbsDependency.successor_id.in_(set(current)),
    ).delete(synchronize_session=False)
    for dependency in validated.dependencies:
        db.add(
            models.WbsDependency(
                predecessor_id=id_map[dependency.predecessor_id],
                successor_id=id_map[dependency.successor_id],
                reason=dependency.reason,
            )
        )


def decide_proposal(db: Session, proposal_id: int, payload: schemas.WbsChangeProposalDecisionCreate) -> schemas.WbsChangeProposalRead:
    proposal = db.get(models.WbsChangeProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="WBS change proposal not found")
    if proposal.status != "draft":
        raise HTTPException(status_code=409, detail="WBS change proposal has already been decided")
    root = get_root_or_404(db, proposal.root_id)
    if payload.decision == "approved":
        updated = (
            db.query(models.WbsNode)
            .filter(models.WbsNode.id == root.id, models.WbsNode.version == proposal.base_version)
            .update({models.WbsNode.version: proposal.base_version + 1}, synchronize_session=False)
        )
        if updated != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="WBS root version has changed since proposal creation")
        root.version = proposal.base_version + 1
        apply_snapshot(
            db,
            root,
            schemas.WbsChangeSnapshot.model_validate(task_service.decode_json(proposal.after_json)),
            root.version,
        )
        proposal.status = "approved"
        event_type = "wbs_change_approved"
    else:
        proposal.status = "rejected"
        event_type = "wbs_change_rejected"
    proposal.decided_by_id = payload.decided_by_id
    proposal.decision_note = payload.note
    proposal.decided_at = models.utcnow()
    commit_with_event(
        db,
        root.id,
        event_type,
        {"proposal_id": proposal.id, "root_id": root.id, "decision": payload.decision},
    )
    return proposal_read(proposal)
