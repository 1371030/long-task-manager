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

approve_wbs_proposal() {
  local proposal_id="$1"
  request POST "/wbs/change-proposals/$proposal_id/decision" '{"decision":"approved","note":"Approved in v0.4 demo","decided_by_id":"demo-reviewer"}'
}

create_wbs_child() {
  local parent_id="$1"
  local title="$2"
  local position="$3"
  local proposal proposal_id tree
  proposal="$(request POST "/wbs/$parent_id/children" "{\"title\":\"$title\",\"node_type\":\"work\",\"position\":$position}")"
  proposal_id="$(echo "$proposal" | jq -r '.id')"
  [[ "$proposal_id" =~ ^[0-9]+$ ]] || fail "WBS child proposal id was not returned"
  echo "$proposal" | jq -e '.status == "draft"' >/dev/null || fail "WBS child proposal was not a draft"
  approve_wbs_proposal "$proposal_id" >/dev/null
  tree="$(request GET "/tasks/$task_id/wbs")"
  echo "$tree" | jq -r --arg title "$title" '.nodes[] | select(.title == $title) | .id'
}

create_wbs_dependency() {
  local root_id="$1"
  local predecessor_id="$2"
  local successor_id="$3"
  local proposal proposal_id
  proposal="$(request POST "/wbs/$root_id/dependencies" "{\"predecessor_id\":$predecessor_id,\"successor_id\":$successor_id}")"
  proposal_id="$(echo "$proposal" | jq -r '.id')"
  [[ "$proposal_id" =~ ^[0-9]+$ ]] || fail "WBS dependency proposal id was not returned"
  approve_wbs_proposal "$proposal_id" >/dev/null
}

require_jq

health="$(request GET /health)"
echo "$health" | require_json
[[ "$(echo "$health" | jq -r '.status')" == "ok" ]] || fail "/health did not return status ok"
[[ "$(echo "$health" | jq -r '.version')" == "0.4.0" ]] || fail "/health did not return version 0.4.0"

created_task="$(request POST /tasks '{"title":"Demo long task","goal":"我想做一个长时间任务管理系统，支持阶段、多次执行、审核和进度观测。","initial_message":"我想做一个长时间任务管理系统，支持阶段、多次执行、审核和进度观测。"}')"
task_id="$(echo "$created_task" | jq -r '.id')"
[[ "$task_id" =~ ^[0-9]+$ ]] || fail "task_id was not returned"

wbs_tree="$(request POST "/tasks/$task_id/wbs-nodes" '{"title":"Demo work breakdown","description":"Independent planning layer for the demo"}')"
wbs_root_id="$(echo "$wbs_tree" | jq -r '.root_id')"
[[ "$wbs_root_id" =~ ^[0-9]+$ ]] || fail "WBS root_id was not returned"
echo "$wbs_tree" | jq -e --argjson task_id "$task_id" --argjson root_id "$wbs_root_id" '.version == 1 and .root_id == $root_id and (.nodes | length == 1) and .nodes[0].id == $root_id and .nodes[0].execution_task_id == $task_id and .rollup.progress_percent == 0' >/dev/null || fail "initial WBS tree is incorrect"

main_start_id="$(create_wbs_child "$wbs_root_id" "Main chain start" 1)"
main_finish_id="$(create_wbs_child "$wbs_root_id" "Main chain finish" 2)"
feeding_id="$(create_wbs_child "$wbs_root_id" "Feeding chain" 3)"
for node_id in "$main_start_id" "$main_finish_id" "$feeding_id"; do
  [[ "$node_id" =~ ^[0-9]+$ ]] || fail "WBS child node id was not returned"
done
create_wbs_dependency "$wbs_root_id" "$main_start_id" "$main_finish_id"
create_wbs_dependency "$wbs_root_id" "$feeding_id" "$main_finish_id"

main_start_revision="$(request POST "/wbs/$main_start_id/estimate-revisions" '{"base_revision":0,"estimate_category":" Demo   API ","manual_estimate":{"optimistic":1,"most_likely":2,"pessimistic":4},"reason":"Deterministic main-chain estimate","created_by_id":"demo-user"}')"
main_finish_revision="$(request POST "/wbs/$main_finish_id/estimate-revisions" '{"base_revision":0,"estimate_category":" Demo   API ","manual_estimate":{"optimistic":1,"most_likely":1,"pessimistic":1},"reason":"Deterministic finish estimate","created_by_id":"demo-user"}')"
feeding_revision="$(request POST "/wbs/$feeding_id/estimate-revisions" '{"base_revision":0,"estimate_category":" Demo   API ","manual_estimate":{"optimistic":0.5,"most_likely":1,"pessimistic":1.5},"reason":"Deterministic feeding-chain estimate","created_by_id":"demo-user"}')"
for revision in "$main_start_revision" "$main_finish_revision" "$feeding_revision"; do
  echo "$revision" | jq -e '.revision_number == 1 and .estimate_category == "demo-api" and (.optimistic_ms | type == "number") and (.most_likely_ms | type == "number") and (.pessimistic_ms | type == "number") and .optimistic_ms >= 0 and .most_likely_ms >= .optimistic_ms and .pessimistic_ms >= .most_likely_ms' >/dev/null || fail "manual estimate revision was not normalized and persisted as integer milliseconds"
done

echo "$main_start_revision" | jq -e '.optimistic_ms == 3600000 and .most_likely_ms == 7200000 and .pessimistic_ms == 14400000' >/dev/null || fail "Decimal hours were not converted deterministically to milliseconds"

request POST "/tasks/$task_id/messages" '{"message":"不使用 Docker，先本地运行，每个阶段可以反复执行。"}' >/dev/null

plan="$(request POST "/tasks/$task_id/generate-plan" '{"reason":"Demo plan","steps":[{"title":"确认任务流程","objective":"确认任务、阶段、多次执行、审核和进度观测流程。","estimate_category":"demo-api"},{"title":"执行演示运行","objective":"启动一次 StepRun，提交结果并完成审核。","estimate_category":"demo-api"}]}')"
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

wbs_before_estimate_get="$(request GET "/tasks/$task_id/wbs")"
detail_before_estimate_get="$(request GET "/tasks/$task_id")"
timeline_before_estimate_get="$(request GET "/tasks/$task_id/timeline")"
estimate_buffer="$(request GET "/tasks/$task_id/wbs/estimate-buffer")"
estimate_buffer_repeat="$(request GET "/tasks/$task_id/wbs/estimate-buffer")"
wbs_after_estimate_get="$(request GET "/tasks/$task_id/wbs")"
detail_after_estimate_get="$(request GET "/tasks/$task_id")"
timeline_after_estimate_get="$(request GET "/tasks/$task_id/timeline")"

[[ "$(echo "$estimate_buffer" | jq -S -c .)" == "$(echo "$estimate_buffer_repeat" | jq -S -c .)" ]] || fail "estimate-buffer GET did not return stable output"
[[ "$(echo "$wbs_before_estimate_get" | jq -S -c .)" == "$(echo "$wbs_after_estimate_get" | jq -S -c .)" ]] || fail "estimate-buffer GET mutated WBS structure"
[[ "$(echo "$detail_before_estimate_get" | jq -S -c '{task,steps,progress,current_pointer,next_actions}')" == "$(echo "$detail_after_estimate_get" | jq -S -c '{task,steps,progress,current_pointer,next_actions}')" ]] || fail "estimate-buffer GET mutated execution state"
[[ "$(echo "$timeline_before_estimate_get" | jq -S -c .)" == "$(echo "$timeline_after_estimate_get" | jq -S -c .)" ]] || fail "estimate-buffer GET emitted events"

echo "$estimate_buffer" | jq -e \
  --argjson root_id "$wbs_root_id" \
  --argjson version "$(echo "$wbs_before_estimate_get" | jq '.version')" \
  --argjson main_start "$main_start_id" \
  --argjson main_finish "$main_finish_id" \
  --argjson feeding "$feeding_id" '
    .availability == "available" and
    .root_id == $root_id and
    .wbs_version == $version and
    ([.node_estimates[] | select(.node_id == $main_start or .node_id == $main_finish or .node_id == $feeding)] | length == 3) and
    all(.node_estimates[] | select(.node_id == $main_start or .node_id == $main_finish or .node_id == $feeding); .source == "manual" and .availability == "available" and .estimate_category == "demo-api" and .latest_revision == 1 and .sample_count == 0) and
    .schedule.availability == "available" and
    .schedule.node_ids == [$main_start, $main_finish] and
    (.feeding_buffers | length == 1) and
    .feeding_buffers[0].path_node_ids == [$feeding] and
    .feeding_buffers[0].join_node_id == $main_finish and
    .project_buffer.recommended_ms >= 0 and
    (.project_buffer.consumed_ms == null or .project_buffer.consumed_ms >= 0) and
    (.project_buffer.remaining_ms == null or .project_buffer.remaining_ms >= 0) and
    all(.feeding_buffers[]; .recommended_ms >= 0 and (.consumed_ms == null or .consumed_ms >= 0) and (.remaining_ms == null or .remaining_ms >= 0))
  ' >/dev/null || fail "estimate and buffer response is incorrect"

wbs_tree="$wbs_after_estimate_get"
timeline="$timeline_after_estimate_get"
timeline_count="$(echo "$timeline" | jq 'length')"
[[ "$timeline_count" -gt 0 ]] || fail "timeline is empty"
echo "$timeline" | jq -e 'any(.[]; .event_type == "progress_review_created") and any(.[]; .event_type == "progress_review_decided") and any(.[]; .event_type == "wbs_estimate_revision_created")' >/dev/null || fail "expected timeline events are missing"

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
  --argjson wbs_version "$(echo "$wbs_tree" | jq '.version')" \
  --argjson project_buffer_ms "$(echo "$estimate_buffer" | jq '.project_buffer.recommended_ms')" \
  --argjson feeding_buffers_count "$(echo "$estimate_buffer" | jq '.feeding_buffers | length')" \
  '{task_id: $task_id, task_status: $task_status, steps_count: $steps_count, approved_steps: $approved_steps, progress_percent: $progress_percent, progress_reviews_count: $progress_reviews_count, wbs_root_id: $wbs_root_id, wbs_version: $wbs_version, project_buffer_ms: $project_buffer_ms, feeding_buffers_count: $feeding_buffers_count, timeline_count: $timeline_count, artifacts_count: $artifacts_count, next_actions_count: $next_actions_count}'
