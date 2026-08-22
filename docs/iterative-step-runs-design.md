# Iterative Step Runs Design

English | [简体中文](iterative-step-runs-design.zh-CN.md)

## Core Principles

A Step is not a one-time result.

A Step represents “a unit of work to be completed,” rather than “a slot that is executed once and stores one unique result.” Each actual execution attempt is represented by a `StepRun`.

## Why StepRun Exists

During long-running tasks, the same step often goes through multiple attempts:
- Initial execution
- Returned after human review
- Rerun after revision
- Run again after changing the executor
- Parallel solution experiments

The system must therefore separate the “step definition” from the “execution attempt.”

## Separation of Responsibilities Between Step and StepRun

### Step is responsible for
- Expressing the step objective
- Participating in task structure orchestration
- Carrying aggregated status
- Supporting insertion, skipping, replacement, forking, and merging

### StepRun is responsible for
- Recording one concrete execution attempt
- Recording input, output, errors, duration, and executor
- Carrying capability invocation records
- Carrying review results

## Multiple Runs Per Step

Each Step can have multiple `StepRun`s.

A typical lifecycle:
1. Create a Step
2. Initiate the first StepRun
3. Submit the result after execution ends
4. Review as accepted or rejected
5. If `needs_revision` or `rejected`, initiate a new StepRun

Historical Runs are never overwritten.

This means:
- `run_1` remains after failing
- `run_2` remains after being returned
- `run_3` must also remain after being accepted; preceding records must not be deleted

## Run Status Model

A Run can be in one of the following states:
- `running`
- `submitted`
- `accepted`
- `rejected`
- `failed`
- `cancelled`

At minimum, the following key business states should be supported:
- `submitted`
- `accepted`
- `rejected`
- `failed`

## Review and Rerun Flow

A common flow is as follows:

1. StepRun finishes execution and enters `submitted`
2. The reviewer creates an `Approval`
3. If approved, the StepRun is marked `accepted`
4. If not approved, the StepRun is marked `rejected`
5. If changes are required, the reviewer submits `decision=request_revision`, the run is marked `rejected`, and a new rerun can be triggered

`request_revision` does not mean overwriting the original run record; it leads to a new `StepRun` while preserving the rejected attempt.

## Dynamic Step Evolution

A Step cannot be treated as a fixed array that is completely determined when the task begins.

The system must support:
- Dynamically adding a step
- Inserting a step at any position
- Skipping a step
- Replacing an existing step with a new step
- Expanding subsequent steps based on results during execution

This allows the plan to evolve as understanding of the task changes.

## Forking Variants

When a step has multiple viable approaches, Step should support forking into multiple parallel variants.

For example:
- Option A
- Option B
- Option C

Each variant can independently have:
- Its own StepRun history
- Its own substeps
- Its own artifacts and approval records

## Copying Substep Trees

When a Step forks into parallel variants, the system can copy the existing substep tree to each variant branch.

The purpose is to:
- Give different approaches symmetrical execution structures
- Make it easier to compare the results of the same steps under different approaches
- Avoid limiting variant implementation to a single step level

## Comparing Variants

Variants can be executed and compared in parallel.

The system needs to support at least:
- Grouping multiple variants into the same comparison group
- Recording each variant’s status, artifacts, and run results
- Allowing reviewers to inspect differences and provide a selection decision

## Selecting the Final Variant

After comparison is complete, one of the variants must be selected to enter the mainline.

The selection result should satisfy the following:
- Mark the selected variant as the final approach
- Preserve the historical record of unselected variants
- Continue subsequent mainline steps by inheriting from the selected variant

## Design Summary

This design ensures that:
- Step is a structural node, not a container for one unique result
- StepRun is the true carrier of execution history
- Historical runs are never overwritten
- Plans can continue evolving during execution
- Parallel approaches can be compared systematically rather than assembled ad hoc
