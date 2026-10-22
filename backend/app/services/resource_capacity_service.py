from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from . import wbs_service

HOURS_TO_MINUTES = Decimal("60")


def hours_to_minutes(hours: Decimal) -> int:
    value = (hours * HOURS_TO_MINUTES).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if value > Decimal("9223372036854775807"):
        raise HTTPException(status_code=422, detail="hours exceed supported integer range")
    return int(value)


def monday_or_422(value: date) -> date:
    if value.weekday() != 0:
        raise HTTPException(status_code=422, detail="week_start must be a Monday")
    return value


def resource_read(resource: models.PlanningResource) -> schemas.PlanningResourceRead:
    hours = None if resource.weekly_capacity_minutes is None else Decimal(resource.weekly_capacity_minutes) / HOURS_TO_MINUTES
    return schemas.PlanningResourceRead(id=resource.id, name=resource.name, weekly_capacity_hours=hours)


def create_resource(db: Session, payload: schemas.PlanningResourceCreate) -> schemas.PlanningResourceRead:
    resource = models.PlanningResource(name=payload.name, weekly_capacity_minutes=None if payload.weekly_capacity_hours is None else hours_to_minutes(payload.weekly_capacity_hours))
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource_read(resource)


def list_resources(db: Session) -> list[schemas.PlanningResourceRead]:
    return [resource_read(item) for item in db.query(models.PlanningResource).order_by(models.PlanningResource.name, models.PlanningResource.id).all()]


def atomic_work_node(db: Session, node_id: int) -> models.WbsNode:
    node = db.get(models.WbsNode, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="WBS node not found")
    active_child = db.query(models.WbsNode.id).filter(models.WbsNode.parent_id == node_id, models.WbsNode.is_active.is_(True)).first()
    if not node.is_active or node.node_type != "work" or active_child is not None:
        raise HTTPException(status_code=422, detail="this operation requires an active atomic work node")
    return node


def upsert_skill(db: Session, resource_id: int, payload: schemas.ResourceSkillUpsert) -> None:
    resource = db.get(models.PlanningResource, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="planning resource not found")
    item = db.query(models.ResourceSkill).filter_by(resource_id=resource_id, name=payload.name).one_or_none()
    if item is None:
        item = models.ResourceSkill(resource_id=resource_id, name=payload.name, proficiency=payload.proficiency)
        db.add(item)
    else:
        item.proficiency = payload.proficiency
    db.commit()


def upsert_capacity(db: Session, resource_id: int, payload: schemas.ResourceWeekCapacityUpsert) -> None:
    resource = db.get(models.PlanningResource, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="planning resource not found")
    week_start = monday_or_422(payload.week_start)
    item = db.query(models.ResourceWeekCapacity).filter_by(resource_id=resource_id, week_start=week_start).one_or_none()
    minutes = hours_to_minutes(payload.capacity_hours)
    if item is None:
        db.add(models.ResourceWeekCapacity(resource_id=resource_id, week_start=week_start, capacity_minutes=minutes))
    else:
        item.capacity_minutes = minutes
    db.commit()


def upsert_requirement(db: Session, node_id: int, payload: schemas.WbsSkillRequirementUpsert) -> None:
    node = atomic_work_node(db, node_id)
    item = db.query(models.WbsSkillRequirement).filter_by(node_id=node_id, name=payload.name).one_or_none()
    if item is None:
        db.add(models.WbsSkillRequirement(node_id=node_id, name=payload.name, minimum_proficiency=payload.minimum_proficiency))
    else:
        item.minimum_proficiency = payload.minimum_proficiency
    db.commit()


def upsert_allocation(db: Session, node_id: int, payload: schemas.WbsWeekAllocationUpsert) -> None:
    node = atomic_work_node(db, node_id)
    resource = db.get(models.PlanningResource, payload.resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="planning resource not found")
    week_start = monday_or_422(payload.week_start)
    item = db.query(models.WbsWeekAllocation).filter_by(resource_id=resource.id, node_id=node.id, week_start=week_start).one_or_none()
    minutes = hours_to_minutes(payload.planned_hours)
    if item is None:
        db.add(models.WbsWeekAllocation(resource_id=resource.id, node_id=node.id, week_start=week_start, planned_minutes=minutes))
    else:
        item.planned_minutes = minutes
    db.commit()


def delete_resource(db: Session, resource_id: int) -> None:
    resource = db.get(models.PlanningResource, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="planning resource not found")
    for model in (models.ResourceSkill, models.ResourceWeekCapacity, models.WbsWeekAllocation):
        db.query(model).filter(model.resource_id == resource_id).delete(synchronize_session=False)
    db.delete(resource)
    db.commit()


def delete_resource_skill(db: Session, resource_id: int, name: str) -> None:
    delete_planning_record(db, models.ResourceSkill, resource_id=resource_id, name=name, detail="resource skill not found")


def delete_resource_capacity(db: Session, resource_id: int, week_start: date) -> None:
    week_start = monday_or_422(week_start)
    delete_planning_record(db, models.ResourceWeekCapacity, resource_id=resource_id, week_start=week_start, detail="weekly capacity override not found")


def delete_skill_requirement(db: Session, node_id: int, name: str) -> None:
    delete_planning_record(db, models.WbsSkillRequirement, node_id=node_id, name=name, detail="WBS skill requirement not found")


def delete_allocation(db: Session, node_id: int, resource_id: int, week_start: date) -> None:
    week_start = monday_or_422(week_start)
    delete_planning_record(db, models.WbsWeekAllocation, node_id=node_id, resource_id=resource_id, week_start=week_start, detail="weekly allocation not found")


def delete_planning_record(db: Session, model: type, detail: str, **filters: object) -> None:
    item = db.query(model).filter_by(**filters).one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail=detail)
    db.delete(item)
    db.commit()


def read_capacity(db: Session, root_id: int, week_start: date) -> schemas.ResourceCapacityReport:
    week_start = monday_or_422(week_start)
    root = wbs_service.get_root_or_404(db, root_id)
    nodes = wbs_service.tree_nodes(db, root_id)
    ordered = wbs_service.depth_first(nodes, root_id)
    children = wbs_service.children_by_parent(nodes)
    atomic_ids = {node.id for node in nodes if node.is_active and node.node_type == "work" and not any(child.is_active for child in children.get(node.id, []))}
    tree = wbs_service.read_tree(db, root_id)
    status_by_id = {node.id: node.status for node in tree.nodes}
    all_nodes = db.query(models.WbsNode).all()
    all_children: dict[int, list[models.WbsNode]] = {}
    for item in all_nodes:
        all_children.setdefault(item.parent_id or 0, []).append(item)
    active_roots = {
        item.id: item
        for item in all_nodes
        if item.parent_id is None and item.is_active
    }
    excluded_node_ids = {
        item.id
        for item in all_nodes
        if item.execution_task_id is not None
        and (task := db.get(models.Task, item.execution_task_id)) is not None
        and task.status in wbs_service.EXCLUDED_TASK_STATUSES
    }
    excluded_root_ids = {
        root_id
        for root_id, candidate_root in active_roots.items()
        if candidate_root.id in excluded_node_ids
    }
    all_atomic_active = {
        item.id
        for item in all_nodes
        if item.root_id not in excluded_root_ids
        and item.id not in excluded_node_ids
        and item.is_active
        and item.node_type == "work"
        and not any(child.is_active for child in all_children.get(item.id, []))
    }
    unfinished_global: set[int] = set()
    for candidate_root_id in active_roots:
        if candidate_root_id in excluded_root_ids:
            continue
        candidate_tree = wbs_service.read_tree(db, candidate_root_id)
        unfinished_global.update(item.id for item in candidate_tree.nodes if item.id in all_atomic_active and item.status != "completed")
    valid_ids = {
        node_id
        for node_id in atomic_ids
        if node_id in unfinished_global and status_by_id[node_id] != "completed"
    }
    all_allocations = db.query(models.WbsWeekAllocation).filter(models.WbsWeekAllocation.week_start == week_start).all()
    effective_allocations = [item for item in all_allocations if item.node_id in unfinished_global]
    allocations = [item for item in effective_allocations if item.node_id in valid_ids]
    all_resources = db.query(models.PlanningResource).order_by(models.PlanningResource.name, models.PlanningResource.id).all()
    resource_ids = {item.id for item in all_resources}
    resources = {item.id: item for item in all_resources}
    capacities = {item.resource_id: item for item in db.query(models.ResourceWeekCapacity).filter(models.ResourceWeekCapacity.week_start == week_start, models.ResourceWeekCapacity.resource_id.in_(resource_ids)).all()} if resource_ids else {}
    requirements = {}
    if valid_ids:
        for item in db.query(models.WbsSkillRequirement).filter(models.WbsSkillRequirement.node_id.in_(valid_ids)).all():
            requirements.setdefault(item.node_id, []).append(item)
    skills = {}
    if resource_ids:
        for item in db.query(models.ResourceSkill).filter(models.ResourceSkill.resource_id.in_(resource_ids)).all():
            skills.setdefault(item.resource_id, {})[item.name] = item.proficiency
    node_titles = {node.id: node.title for node in nodes}
    root_minutes = {resource_id: sum(item.planned_minutes for item in allocations if item.resource_id == resource_id) for resource_id in resource_ids}
    report_resources = []
    warnings = []
    for resource_id in sorted(resource_ids):
        resource = resources[resource_id]
        capacity = capacities.get(resource_id)
        available = capacity.capacity_minutes if capacity else resource.weekly_capacity_minutes
        total = root_minutes[resource_id]
        other_minutes = sum(item.planned_minutes for item in effective_allocations if item.resource_id == resource_id and item.node_id not in valid_ids)
        if available is None:
            status = "unknown_capacity"
            percent = None
        elif available == 0:
            status = "zero_capacity" if total + other_minutes else "within_capacity"
            percent = None
        else:
            percent = (Decimal(total + other_minutes) * 100 / Decimal(available)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            status = "over_capacity" if total + other_minutes > available else "within_capacity"
        if status == "over_capacity":
            warnings.append(schemas.CapacityWarningRead(code="resource_over_capacity", message=f"{resource.name} has {Decimal(total + other_minutes) / HOURS_TO_MINUTES} planned hours against {Decimal(available) / HOURS_TO_MINUTES} available hours.", resource_id=resource_id))
        report_resources.append(schemas.ResourceCapacityRead(resource_id=resource_id, resource_name=resource.name, available_hours=None if available is None else Decimal(available) / HOURS_TO_MINUTES, planned_hours=Decimal(total + other_minutes) / HOURS_TO_MINUTES, root_planned_hours=Decimal(total) / HOURS_TO_MINUTES, other_root_planned_hours=Decimal(other_minutes) / HOURS_TO_MINUTES, utilization_percent=percent, status=status))
    report_nodes = []
    suggestions = []
    total_minutes_by_resource = {
        resource_id: sum(item.planned_minutes for item in effective_allocations if item.resource_id == resource_id)
        for resource_id in resource_ids
    }
    for node, _ in ordered:
        if node.id not in valid_ids:
            continue
        node_allocations = [item for item in allocations if item.node_id == node.id]
        requirement_items = requirements.get(node.id, [])
        statuses = []
        reasons = []
        for allocation in node_allocations:
            resource_skills = skills.get(allocation.resource_id, {})
            for requirement in requirement_items:
                proficiency = resource_skills.get(requirement.name)
                if proficiency is None:
                    statuses.append("unknown")
                    reasons.append(f"resource {allocation.resource_id} has no {requirement.name} profile")
                elif proficiency < requirement.minimum_proficiency:
                    statuses.append("gap")
                    reasons.append(f"resource {allocation.resource_id} has {requirement.name} proficiency {proficiency}, requires {requirement.minimum_proficiency}")
                else:
                    statuses.append("met")
        skill_status = "not_required" if not requirement_items else ("gap" if "gap" in statuses else "unknown" if "unknown" in statuses else "met" if statuses else "unknown")
        if not node_allocations:
            warnings.append(schemas.CapacityWarningRead(code="node_unassigned", message=f"{node.title} has no planned allocation for this week.", node_id=node.id))
        if skill_status == "gap":
            warnings.append(schemas.CapacityWarningRead(code="skill_gap", message=f"{node.title} has a proficiency gap.", node_id=node.id))
        if requirement_items and node_allocations and skill_status in {"gap", "unknown"}:
            planned_minutes = sum(item.planned_minutes for item in node_allocations)
            for candidate in all_resources:
                candidate_skills = skills.get(candidate.id, {})
                if any(candidate_skills.get(requirement.name, 0) < requirement.minimum_proficiency for requirement in requirement_items):
                    continue
                candidate_capacity = capacities.get(candidate.id)
                available = candidate_capacity.capacity_minutes if candidate_capacity else candidate.weekly_capacity_minutes
                if available is None or available == 0 or total_minutes_by_resource.get(candidate.id, 0) + planned_minutes > available:
                    continue
                suggestions.append(schemas.CapacitySuggestionRead(node_id=node.id, resource_id=candidate.id, resource_name=candidate.name, message=f"{candidate.name} has the required skills and enough known remaining capacity for {Decimal(planned_minutes) / HOURS_TO_MINUTES} planned hours; review manually."))
        report_nodes.append(schemas.CapacityNodeRead(node_id=node.id, title=node.title, planned_hours=Decimal(sum(item.planned_minutes for item in node_allocations)) / HOURS_TO_MINUTES, resource_ids=sorted({item.resource_id for item in node_allocations}), skill_status=skill_status, reasons=reasons))
    return schemas.ResourceCapacityReport(root_id=root.id, wbs_version=root.version, week_start=week_start, resources=report_resources, nodes=report_nodes, warnings=warnings, suggestions=suggestions, assumptions=["Only explicit weekly allocations are counted as load.", "Utilization aggregates allocations across all WBS roots.", "WBS estimate duration is not converted into resource effort.", "Suggestions are read-only candidates for manual review; no allocation or sequencing is changed.", "This report does not schedule work or promise completion dates."])
