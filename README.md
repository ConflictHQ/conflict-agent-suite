# conflict-agent-suite

Agents only. No deployment, no managed services, nothing standing between runs
— every workload is `kind = "agent"` with `run_family = "task"`, so it spawns as
a Job on dispatch and costs nothing while idle.

## What they actually do

They watch the sibling fixtures rather than inventing work: each run reads the
dashboards' own `/health`, `/selftest` and `/api/summary`, so the output says
something true about the install it ran in.

| Role | Does |
|---|---|
| `triage` | Probes each watched app, classifies it `healthy` / `degraded` / `unreachable`, and flags notable events |
| `summarize` | Turns a triage result into a short brief |
| `review` | States a recommendation for the human gate that follows it |

One image, three roles, selected by `AGENT_ROLE`. Stages hand off through
`ASTROLIFT_AGENT_INPUT`, so `summarize` consumes what `triage` produced.

**Deterministic on purpose.** A demo agent that needs a model endpoint to answer
costs money to idle and fails for reasons unrelated to the thing being shown.

## Workflows

| File | Pattern | Shape |
|---|---|---|
| `workflows/health-sweep.toml` | `chained` | triage → summarize → review → **human_gate** |
| `workflows/triage-only.toml` | `single` | one dispatch, no hand-off — what a schedule points at |

Both pass `astro workflow validate`.

## Running

```sh
astro agent register-repo ConflictHQ/conflict-agent-suite \
  --project-id <demos-project-guid>
astro agent dispatch triage
astro agent logs <task-id>

astro workflow import workflows/health-sweep.toml
astro workflow run health-sweep
```

Agent workloads create Workload rows directly and never roll through the deploy
pipeline, which is why this repo is registered with `agent register-repo`
rather than `app register`.

## A note on exit codes

A triage that finds something critical still exits 0. The finding is the
result, not a failure of the run — a stage failing on a real finding would make
`on_failure = "retry"` loop forever against a genuinely broken app.

## Known gap

`run_mode` (`once` / `loop` / `schedule` / `trigger` / `persistent`) cannot be
declared in `astrolift.toml` — `WorkloadManifest` has no such field, so writing
one parses cleanly and does nothing. Filed as astrolift-app#1680. Until it
lands, the trigger mode is set through the registration API rather than here.
