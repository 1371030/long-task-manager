import re
from typing import Any

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from .. import models, schemas
from ..config import settings

PLANNER_USER_AGENT = "long-task-manager-planner/0.2.1"

def build_plan_prompt(task: models.Task, messages: list[models.TaskMessage], instructions: str | None = None) -> str:
    return build_plan_prompt_for_goal(task.goal, task, messages, instructions)


def build_plan_prompt_for_goal(goal: str, task: models.Task, messages: list[models.TaskMessage], instructions: str | None = None) -> str:
    parts = [f"User request: {goal}"]
    if task.constraints:
        parts.append(f"Constraints: {task.constraints}")
    if messages:
        parts.append(f"Latest note: {messages[-1].message}")
    if instructions and instructions.strip():
        parts.append(f"Extra instructions: {instructions.strip()}")
    return "\n".join(parts)


def plan_llm_call_payload(task: models.Task, messages: list[models.TaskMessage], system_prompt: str, instructions: str | None = None) -> dict[str, Any]:
    request_messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {"role": "user", "content": build_plan_prompt(task, messages, instructions)},
    ]
    return {
        "provider": "openai_compatible",
        "purpose": "plan_generation",
        "api": "chat.completions.create",
        "base_url": settings.api_url,
        "model": settings.api_model,
        "temperature": settings.planner_openai_temperature,
        "timeout_seconds": settings.planner_openai_timeout_seconds,
        "messages": request_messages,
    }



def chat_output_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""


def parse_milestone_steps(content: str) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    lines = [line for line in content.splitlines() if line.strip()]
    paren_chunks = re.findall(r"[^,，;；\n]+[（(][^）)]*[）)]", content)
    if paren_chunks:
        chunks = paren_chunks
    elif len(lines) > 1 or " - " in content or " – " in content or ":" in content:
        chunks = lines if lines else [content]
    else:
        chunks = re.split(r"[,，;；]", content)
    for chunk in chunks:
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", chunk).strip()
        if not cleaned:
            continue
        paren_match = re.match(r"^(.+?)[（(](.+)[）)]$", cleaned)
        if paren_match:
            title, objective = paren_match.groups()
        elif " - " in cleaned:
            title, objective = cleaned.split(" - ", 1)
        elif " – " in cleaned:
            title, objective = cleaned.split(" – ", 1)
        elif ":" in cleaned:
            title, objective = cleaned.split(":", 1)
        else:
            title, objective = cleaned, cleaned
        title = re.sub(r"^\*\*(.*?)\**$", r"\1", title.strip()).strip()
        objective = objective.strip()
        if title and objective:
            steps.append({"title": title, "objective": objective})
    return steps



def post_chat_completion(messages: list[dict[str, str]], max_tokens: int) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"{settings.api_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
                "User-Agent": PLANNER_USER_AGENT,
            },
            json={
                "model": settings.api_model,
                "messages": messages,
                "max_completion_tokens": max_tokens,
                "stream": False,
            },
            timeout=settings.planner_openai_timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Planner service timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Planner service connection failed") from exc

    if response.status_code == 429:
        raise HTTPException(status_code=429, detail="Planner service rate limit exceeded")
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail="Planner service returned an error")

    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Planner returned invalid response JSON") from exc


def generate_plan_steps(task: models.Task, messages: list[models.TaskMessage], system_prompt: str, instructions: str | None = None) -> list[schemas.PlanStepCreate]:
    if not settings.api_key or not settings.api_model:
        raise HTTPException(status_code=503, detail="OpenAI-compatible planner is not configured")

    llm_call = plan_llm_call_payload(task, messages, system_prompt, instructions)
    response_payload = post_chat_completion(llm_call["messages"], max_tokens=128000)

    content = chat_output_text(response_payload)
    if not content:
        raise HTTPException(status_code=502, detail="Planner returned an empty response")

    raw_steps = parse_milestone_steps(content)
    if not raw_steps:
        raise HTTPException(status_code=502, detail="Planner response must include at least one step")

    steps: list[schemas.PlanStepCreate] = []
    for raw_step in raw_steps:
        try:
            step = schemas.PlanStepCreate.model_validate(raw_step)
        except ValidationError as exc:
            raise HTTPException(status_code=502, detail="Planner returned an invalid step") from exc
        if not step.title.strip() or not step.objective.strip():
            raise HTTPException(status_code=502, detail="Planner returned an empty step title or objective")
        steps.append(step)

    return steps
