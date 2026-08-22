import pytest
from fastapi import HTTPException

from app import models, schemas
from app.services import plan_generation_service, task_service
from test_phase1_flow import create_task


def test_auto_generate_plan_creates_steps_with_mocked_planner(client, monkeypatch):
    task = create_task(client)

    client.patch("/settings/planner-prompt", json={"prompt": "Runtime planner prompt"})

    def fake_generate_plan_steps(task_model, messages, system_prompt, instructions=None):
        assert task_model.id == task["id"]
        assert messages[-1].message == "Initial intake"
        assert system_prompt == "Runtime planner prompt"
        assert instructions == "Prefer three stages"
        return [
            schemas.PlanStepCreate(title="Analyze request", objective="Understand the task goal and constraints."),
            schemas.PlanStepCreate(title="Prepare execution plan", objective="Break the work into reviewable steps."),
            schemas.PlanStepCreate(title="Define acceptance", objective="Identify checks for task completion."),
        ]

    monkeypatch.setattr(task_service, "generate_plan_steps", fake_generate_plan_steps)

    response = client.post(
        f"/tasks/{task['id']}/generate-plan",
        json={"generation_mode": "auto", "reason": "LLM decomposition", "instructions": "Prefer three stages"},
    )

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["task"]["status"] == "waiting_plan_review"
    assert [step["title"] for step in detail["steps"]] == ["Analyze request", "Prepare execution plan", "Define acceptance"]

    events = client.get(f"/tasks/{task['id']}/timeline").json()
    plan_event = next(event for event in events if event["event_type"] == "task_plan_generated")
    assert plan_event["payload"]["generation_mode"] == "auto"
    assert plan_event["payload"]["step_count"] == 3
    llm_event = next(event for event in events if event["event_type"] == "llm_call")
    assert llm_event["payload"]["messages"][0]["content"] == "Runtime planner prompt"


def test_planner_prompt_settings_round_trip(client):
    initial = client.get("/settings/planner-prompt")
    assert initial.status_code == 200
    assert initial.json()["configured"] is False
    assert initial.json()["prompt"] is None

    blank = client.patch("/settings/planner-prompt", json={"prompt": "   "})
    assert blank.status_code == 422

    updated = client.patch("/settings/planner-prompt", json={"prompt": "Runtime prompt\nKeep user language."})
    assert updated.status_code == 200
    assert updated.json()["configured"] is True
    assert updated.json()["prompt"] == "Runtime prompt\nKeep user language."

    fetched = client.get("/settings/planner-prompt")
    assert fetched.json()["prompt"] == "Runtime prompt\nKeep user language."


def test_auto_generate_plan_requires_runtime_prompt(client, monkeypatch):
    task = create_task(client)

    def fake_generate_plan_steps(task_model, messages, system_prompt, instructions=None):
        raise AssertionError("planner should not be called without runtime prompt")

    monkeypatch.setattr(task_service, "generate_plan_steps", fake_generate_plan_steps)

    response = client.post(f"/tasks/{task['id']}/generate-plan", json={"generation_mode": "auto"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Planner system prompt is not configured"


def test_manual_generate_plan_still_requires_steps(client):
    task = create_task(client)

    missing_steps = client.post(f"/tasks/{task['id']}/generate-plan", json={"reason": "Manual without steps"})
    assert missing_steps.status_code == 422

    response = client.post(
        f"/tasks/{task['id']}/generate-plan",
        json={"generation_mode": "manual", "steps": [{"title": "Manual step", "objective": "Keep existing behavior."}]},
    )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["steps"][0]["title"] == "Manual step"


def test_intake_next_action_advertises_auto_plan_generation(client):
    task = create_task(client)
    detail = client.get(f"/tasks/{task['id']}").json()
    action = detail["next_actions"][0]

    assert action["action_type"] == "generate_plan"
    assert action["target"] == {"task_id": task["id"]}
    assert action["input_schema"]["generation_mode"] == ["manual", "auto"]
    assert action["input_schema"]["instructions"] == "string"


def test_planner_missing_config_returns_controlled_error(monkeypatch):
    monkeypatch.setattr(plan_generation_service.settings, "api_key", None)
    monkeypatch.setattr(plan_generation_service.settings, "api_model", None)
    task = models.Task(title="T", goal="G", status="intake")

    with pytest.raises(HTTPException) as exc_info:
        plan_generation_service.generate_plan_steps(task, [], "Runtime planner prompt")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "OpenAI-compatible planner is not configured"


def test_planner_invalid_output_returns_controlled_error(monkeypatch):
    def fake_post_chat_completion(messages, max_tokens):
        return {"choices": [{"message": {"content": ""}}]}

    monkeypatch.setattr(plan_generation_service.settings, "api_key", "test-key")
    monkeypatch.setattr(plan_generation_service.settings, "api_model", "test-model")
    monkeypatch.setattr(plan_generation_service, "post_chat_completion", fake_post_chat_completion)
    task = models.Task(title="T", goal="G", status="intake")

    with pytest.raises(HTTPException) as exc_info:
        plan_generation_service.generate_plan_steps(task, [], "Runtime planner prompt")

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Planner returned an empty response"


def test_planner_uses_original_goal_for_milestones(monkeypatch):
    captured_messages = []
    runtime_prompt = "Custom planner prompt that asks for short explanation in parentheses and not a technology keyword"

    def fake_post_chat_completion(messages, max_tokens):
        captured_messages.append(messages)
        return {"choices": [{"message": {"content": "梳理需求（确认计时和声音提醒需求，明确 macOS 应用的核心范围。）"}}]}

    monkeypatch.setattr(plan_generation_service.settings, "api_key", "test-key")
    monkeypatch.setattr(plan_generation_service.settings, "api_model", "test-model")
    monkeypatch.setattr(plan_generation_service.settings, "planner_openai_max_steps", 1)
    monkeypatch.setattr(plan_generation_service, "post_chat_completion", fake_post_chat_completion)
    task = models.Task(title="设计自动计时的macos应用程序，计时完成能有声音提醒", goal="设计自动计时的macos应用程序，计时完成能有声音提醒", status="intake")

    steps = plan_generation_service.generate_plan_steps(task, [], runtime_prompt)

    assert steps == [schemas.PlanStepCreate(title="梳理需求", objective="确认计时和声音提醒需求，明确 macOS 应用的核心范围。")]
    assert len(captured_messages) == 1
    assert captured_messages[0][0]["role"] == "system"
    assert captured_messages[0][0]["content"] == runtime_prompt
    assert "设计自动计时的macos应用程序" in captured_messages[0][1]["content"]
    assert "macOS timer app with sound alert" not in captured_messages[0][1]["content"]


def test_planner_does_not_truncate_to_max_steps(monkeypatch):
    def fake_post_chat_completion(messages, max_tokens):
        return {
            "choices": [
                {
                    "message": {
                        "content": "梳理需求（结合用户目标确认计时模式、提醒方式和应用边界。）\n实现功能（开发计时器状态管理和完成后的声音提醒逻辑。）"
                    }
                }
            ]
        }

    monkeypatch.setattr(plan_generation_service.settings, "api_key", "test-key")
    monkeypatch.setattr(plan_generation_service.settings, "api_model", "test-model")
    monkeypatch.setattr(plan_generation_service.settings, "planner_openai_max_steps", 1)
    monkeypatch.setattr(plan_generation_service, "post_chat_completion", fake_post_chat_completion)
    task = models.Task(title="设计自动计时的macos应用程序，计时完成能有声音提醒", goal="设计自动计时的macos应用程序，计时完成能有声音提醒", status="intake")

    steps = plan_generation_service.generate_plan_steps(task, [], "Runtime planner prompt")

    assert steps == [
        schemas.PlanStepCreate(title="梳理需求", objective="结合用户目标确认计时模式、提醒方式和应用边界。"),
        schemas.PlanStepCreate(title="实现功能", objective="开发计时器状态管理和完成后的声音提醒逻辑。"),
    ]


def test_plan_prompt_preserves_original_task_text():
    task = models.Task(title="设计自动计时的macos应用程序，计时完成能有声音提醒", goal="设计自动计时的macos应用程序，计时完成能有声音提醒", status="intake")

    prompt = plan_generation_service.build_plan_prompt(task, [], None)

    assert "设计自动计时的macos应用程序，计时完成能有声音提醒" in prompt
    assert "macOS timer app with a sound alert" not in prompt


def test_planner_connection_failure_returns_controlled_error(monkeypatch):
    def fake_post_chat_completion(messages, max_tokens):
        raise HTTPException(status_code=502, detail="Planner service connection failed")

    monkeypatch.setattr(plan_generation_service.settings, "api_key", "test-key")
    monkeypatch.setattr(plan_generation_service.settings, "api_model", "test-model")
    monkeypatch.setattr(plan_generation_service, "post_chat_completion", fake_post_chat_completion)
    task = models.Task(title="T", goal="设计自动计时的macos应用程序，计时完成能有声音提醒", status="intake")

    with pytest.raises(HTTPException) as exc_info:
        plan_generation_service.generate_plan_steps(task, [], "Runtime planner prompt")

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Planner service connection failed"
