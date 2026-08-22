from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import settings

PLANNER_PROMPT_KEY = "planner_plan_system_prompt"


def planner_prompt_schema(setting: models.AppSetting | None) -> schemas.PlannerPromptRead:
    prompt = setting.value if setting and setting.value.strip() else None
    return schemas.PlannerPromptRead(
        prompt=prompt,
        configured=prompt is not None,
        updated_at=setting.updated_at if setting else None,
    )


def get_planner_prompt_setting(db: Session) -> models.AppSetting | None:
    return db.get(models.AppSetting, PLANNER_PROMPT_KEY)


def get_planner_prompt(db: Session) -> str | None:
    setting = get_planner_prompt_setting(db)
    if setting is None or not setting.value.strip():
        return None
    return setting.value


def require_planner_prompt(db: Session) -> str:
    prompt = get_planner_prompt(db)
    if prompt is None:
        raise HTTPException(status_code=503, detail="Planner system prompt is not configured")
    return prompt


def update_planner_prompt(db: Session, payload: schemas.PlannerPromptUpdate) -> schemas.PlannerPromptRead:
    setting = get_planner_prompt_setting(db)
    if setting is None:
        setting = models.AppSetting(key=PLANNER_PROMPT_KEY, value=payload.prompt)
        db.add(setting)
    else:
        setting.value = payload.prompt
        setting.updated_at = models.utcnow()
    db.commit()
    db.refresh(setting)
    return planner_prompt_schema(setting)


def read_planner_prompt(db: Session) -> schemas.PlannerPromptRead:
    return planner_prompt_schema(get_planner_prompt_setting(db))


def seed_planner_prompt(db: Session) -> None:
    if get_planner_prompt_setting(db) is not None:
        return
    if settings.planner_plan_system_prompt and settings.planner_plan_system_prompt.strip():
        db.add(models.AppSetting(key=PLANNER_PROMPT_KEY, value=settings.planner_plan_system_prompt))
        db.commit()
