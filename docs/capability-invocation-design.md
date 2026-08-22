# Capability Invocation Design
English | [简体中文](capability-invocation-design.zh-CN.md)

## Design Goals

The system needs to record who called what capability in which context, and what the result was.

For this purpose, the task domain should distinguish three things:
- `executor_type` = who is responsible
- `capability_id` = what capability was called
- `adapter_id` = how the capability is implemented

## Three-Layer Semantic Separation

### executor_type

Represents the responsible party. Only the following are allowed:
- `human`
- `agent`
- `worker`
- `system`
- `codex`

The current implementation supports Codex as an `executor_type` and integration path. It answers the question: **Who is responsible for this execution or initiated action?**

### capability_id

Represents the capability definition.

Examples:
- `call_codex`
- `run_tests`
- `scan_source`
- `generate_report`
- `query_database`
- `browse_url`
- `export_openapi`

It answers the question: **What capability is this call intended to accomplish?**

### adapter_id

Represents the implementation adapter for the capability.

Example forms:
- `codex_adapter`
- `browser_adapter`
- `db_query_adapter`
- `report_export_adapter`

It answers the question: **Through what integration method is this capability implemented?**

## Why Not an Extra Tool Category

The MVP does not define an additional tool-category enum layer.

Capability calls are expressed only through:
- `capability_id`
- `adapter_id`
- `handler_name`

These express the capability semantics, implementation adapter, and concrete handling entry point.

Reasons:
- These categories elevate the implementation medium into a primary domain concept
- They confuse both what the capability is and who is executing it
- For the task system, the more stable abstraction is capability + adapter + handler

## Skill Positioning

Skill should not be an independent entity.

If a capability is exposed in the form of a skill, the skill is merely one expression or integration method for `Capability`; it should still be recorded as:
- One `capability_id`
- One `adapter_id`
- One `handler_name`

## Codex Positioning

Codex is a supported `executor_type` and integration path in the current implementation. It may also appear as:
- An example of an adapter implementation for a capability
- An example of an optional external execution integration path

The current optional Codex/tmux integration and optional OpenAI-compatible textual execution are explicitly bounded integration paths; they do not imply support for arbitrary command execution.

This does not change the separate capability/adapter/handler distinction.

## CapabilityInvocation Entity

`CapabilityInvocation` represents a record of one capability call.

Fields include:
- `task_id`
- `step_id`
- `run_id`
- `invoked_by_type`
- `capability_id`
- `adapter_id`
- `handler_name`
- `status`
- `input`
- `output`
- `error`
- `artifacts`
- `duration_ms`

Suggested additional fields:
- `id`
- `invoked_by_id`
- `created_at`
- `ended_at`

## Field Notes

### task_id / step_id / run_id

Define the task context in which the call occurred.

### invoked_by_type

Indicates who initiated the call. `CapabilityInvocation.invoked_by_type` remains separate from `executor_type` and allows only:
- `human`
- `agent`
- `worker`
- `system`

It excludes `codex`; Codex is represented as a supported `executor_type` or integration path, while the capability/adapter/handler distinction remains unchanged.

### capability_id

References the capability definition, such as `run_tests`.

### adapter_id

Represents the capability integration implementation, such as the type of adapter used to forward the call to a specific external system.

### handler_name

Represents the actual internal system handling entry point, such as the name of a handler, service method, or integration route.

### status

Allows exactly:
- `pending`
- `running`
- `succeeded`
- `failed`
- `blocked`
- `cancelled`

### input / output / error

Store the call input, structured output, and error information, respectively.

### artifacts

Represents the set of artifacts associated with this call. It may be a list of artifact IDs or references to related objects.

### duration_ms

Records execution duration for subsequent analysis and auditing.

## Example Interpretation

A record can be understood as:
- An `agent`
- In a particular task's step and a particular run
- Calling the `scan_source` capability
- Implemented through an adapter such as `browser_adapter` or `codex_adapter`
- Actually handled by a particular `handler_name`
- Producing output, error information, and artifacts

## Design Summary

The focus of this model is:
- Use `executor_type` to express the responsible party
- Use `capability_id` to express capability semantics
- Use `adapter_id` and `handler_name` to express the implementation method
- Do not elevate skill, Codex, CLI, browser, database, or file directly into core task-domain types
