#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"

fail() {
  echo "demo_flow.sh: $*" >&2
  exit 1
}

require_jq() {
  command -v jq >/dev/null 2>&1 || fail "jq is required"
}

request() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local response_file status
  response_file="$(mktemp)"

  if [[ -n "$body" ]]; then
    status="$(curl -sS -o "$response_file" -w "%{http_code}" -X "$method" "$API_BASE_URL$path" -H "Content-Type: application/json" -d "$body")" || {
      rm -f "$response_file"
      fail "$method $path failed to connect"
    }
  else
    status="$(curl -sS -o "$response_file" -w "%{http_code}" -X "$method" "$API_BASE_URL$path")" || {
      rm -f "$response_file"
      fail "$method $path failed to connect"
    }
  fi

  if [[ "$status" -lt 200 || "$status" -ge 300 ]]; then
    cat "$response_file" >&2
    rm -f "$response_file"
    fail "$method $path returned HTTP $status"
  fi

  cat "$response_file"
  rm -f "$response_file"
}

require_json() {
  jq -e . >/dev/null || fail "response is not valid JSON"
}

require_jq

health="$(request GET /health)"
echo "$health" | require_json
[[ "$(echo "$health" | jq -r '.status')" == "ok" ]] || fail "/health did not return status ok"
[[ "$(echo "$health" | jq -r '.version')" == "0.3.0" ]] || fail "/health did not return version 0.3.0"

created_task="$(request POST /tasks '{"title":"Demo long task","goal":"我想做一个长时间任务管理系统，支持阶段、多次执行、审核和进度观测。","initial_message":"我想做一个长时间任务管理系统，支持阶段、多次执行、审核和进度观测。"}')"
task_id="$(echo "$created_task" | jq -r '.id')"
[[ "$task_id" =~ ^[0-9]+$ ]] || fail "task_id was not returned"

wbs_tree="$(request POST "/tasks/$task_id/wbs-nodes" '{"title":"Demo work breakdown","description":"Independent planning layer for the demo"}')"
wbs_root_id="$(echo "$wbs_tree" | jq -r '.root_id')"
[[ "$wbs_root_id" =~ ^[0-9]+$ ]] || fail "WBS root_id was not returned"
echo "$wbs_tree" | jq -e --argjson task_id "$task_id" --argjson root_id "$wbs_root_id" '.version == 1 and .root_id == $root_id and (.nodes | length == 1) and .nodes[0].id == $root_id and .nodes[0].execution_task_id == $task_id and .rollup.progress_percent == 0' >/dev/null || fail "initial WBS tree is incorrect"
wbs_tree="$(request GET "/tasks/$task_id/wbs")"
echo "$wbs_tree" | jq -e --argjson root_id "$wbs_root_id" '.root_id == $root_id and .version == 1' >/dev/null || fail "WBS tree read is incorrect"

request POST "/tasks/$task_id/messages" '{"message":"不使用 Docker，先本地运行，每个阶段可以反复执行。"}' >/dev/null

plan="$(request POST "/tasks/$task_id/generate-plan" '{"reason":"Demo plan","steps":[{"title":"确认任务流程","objective":"确认任务、阶段、多次执行、审核和进度观测流程。"},{"title":"执行演示运行","objective":"启动一次 StepRun，提交结果并完成审核。"}]}')"
steps_count="$(echo "$plan" | jq '.steps | length')"
[[ "$steps_count" -gt 0 ]] || fail "generate-plan did not return steps"

approved_plan="$(request POST "/tasks/$task_id/approve-plan" '{"decision":"approved"}')"
[[ "$(echo "$approved_plan" | jq -r '.task.status')" == "planned" ]] || fail "approve-plan did not set task.status=planned"

steps="$(request GET "/tasks/$task_id/steps")"
step_id="$(echo "$steps" | jq -r '.[0].id')"
[[ "$step_id" =~ ^[0-9]+$ ]] || fail "first step_id was not returned"

run="$(request POST "/tasks/$task_id/steps/$step_id/runs" '{"executor_type":"human","executor_ref":"demo-user","input":{"instruction":"Run the demo step"}}')"
run_id="$(echo "$run" | jq -r '.id')"
[[ "$run_id" =~ ^[0-9]+$ ]] || fail "run_id was not returned"

request POST "/tasks/$task_id/steps/$step_id/runs/$run_id/submit" '{"output":{"summary":"Demo run completed"}}' >/dev/null
request POST "/tasks/$task_id/steps/$step_id/runs/$run_id/review" '{"decision":"approved","note":"Approved in demo"}' >/dev/null

detail="$(request GET "/tasks/$task_id")"
progress_percent="$(echo "$detail" | jq -r '.progress.progress_percent')"
echo "$detail" | jq -e '.current_pointer' >/dev/null || fail "current_pointer is missing"
echo "$detail" | jq -e '.next_actions | type == "array"' >/dev/null || fail "next_actions is not an array"
echo "$detail" | jq -e --argjson task_id "$task_id" '(.next_actions | length == 0) or all(.next_actions[]; .target.task_id == $task_id and (if (.target.step_id? != null) then (.target.step_id | type == "number") else true end) and (if (.target.run_id? != null) then (.target.run_id | type == "number") else true end))' >/dev/null || fail "next_actions targets are missing required ids"
echo "$detail" | jq -e '.progress.progress_percent == 50' >/dev/null || fail "progress_percent is not 50"

progress_review="$(request POST "/tasks/$task_id/progress-reviews" '{"expected_progress_percent":75,"created_by_id":"demo-reviewer"}')"
review_id="$(echo "$progress_review" | jq -r '.id')"
[[ "$review_id" =~ ^[0-9]+$ ]] || fail "progress review id was not returned"
echo "$progress_review" | jq -e '.actual_progress_percent == 50 and .variance_percentage_points == -25 and .classification == "behind"' >/dev/null || fail "progress review variance is incorrect"
echo "$progress_review" | jq -e '.snapshot.active_steps_total == 2 and .snapshot.approved_or_skipped_active_steps == 1' >/dev/null || fail "progress review snapshot is incorrect"
echo "$progress_review" | jq -e 'any(.suggestions[]; .action_type == "review_remaining_steps")' >/dev/null || fail "progress review suggestion is missing"

review_decision="$(request POST "/tasks/$task_id/progress-reviews/$review_id/decision" '{"decision":"keep_plan","note":"Continue the demo plan","decided_by_id":"demo-reviewer"}')"
echo "$review_decision" | jq -e '.decision == "keep_plan" and .decision_note == "Continue the demo plan"' >/dev/null || fail "progress review decision was not saved"

progress_reviews="$(request GET "/tasks/$task_id/progress-reviews")"
echo "$progress_reviews" | jq -e --argjson review_id "$review_id" 'length == 1 and .[0].id == $review_id and .[0].previous_review_id == null' >/dev/null || fail "progress review history is incorrect"

timeline="$(request GET "/tasks/$task_id/timeline")"
timeline_count="$(echo "$timeline" | jq 'length')"
[[ "$timeline_count" -gt 0 ]] || fail "timeline is empty"
echo "$timeline" | jq -e 'any(.[]; .event_type == "progress_review_created") and any(.[]; .event_type == "progress_review_decided")' >/dev/null || fail "progress review timeline events are missing"

artifacts="$(request GET "/tasks/$task_id/artifacts")"
echo "$artifacts" | jq -e 'type == "array"' >/dev/null || fail "artifacts response is not an array"

final_status="$(echo "$detail" | jq -r '.task.status')"
[[ "$final_status" == "waiting_review" || "$final_status" == "running" || "$final_status" == "planned" || "$final_status" == "completed" ]] || fail "unexpected final task status: $final_status"

jq -n \
  --arg task_id "$task_id" \
  --arg task_status "$final_status" \
  --argjson steps_count "$(echo "$detail" | jq '.steps | length')" \
  --argjson approved_steps "$(echo "$detail" | jq '[.steps[] | select(.status == "approved")] | length')" \
  --argjson progress_percent "$progress_percent" \
  --argjson timeline_count "$timeline_count" \
  --argjson artifacts_count "$(echo "$artifacts" | jq 'length')" \
  --argjson next_actions_count "$(echo "$detail" | jq '.next_actions | length')" \
  --argjson progress_reviews_count "$(echo "$progress_reviews" | jq 'length')" \
  --argjson wbs_root_id "$wbs_root_id" \
  --argjson wbs_progress_percent "$(echo "$wbs_tree" | jq '.rollup.progress_percent')" \
  '{task_id: $task_id, task_status: $task_status, steps_count: $steps_count, approved_steps: $approved_steps, progress_percent: $progress_percent, progress_reviews_count: $progress_reviews_count, wbs_root_id: $wbs_root_id, wbs_progress_percent: $wbs_progress_percent, timeline_count: $timeline_count, artifacts_count: $artifacts_count, next_actions_count: $next_actions_count}'
