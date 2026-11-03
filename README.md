# Failure-Propagation-and-Recovery-in-Multi-Agent-Systems
Measuring how faults spread through a researcher → planner → executor agent team working on a codebase, and how the team can recover without redoing all its work.

**Status: Phase 1. Environment, tasks T01–T03, tools, tracing and agents built; T01 runs end to end with no faults.** See `CLAUDE.md` for how the experiment is built and `design.md` for the environment and tasks.

## Layout

| Path | What it is |
|---|---|
| `env/lifeline/` | **Lifeline**, a fictional disaster-relief codebase the agents work on (about 20 small Python files, its own tests, seed data in `data/`). It is its own Git repo ([avimehta30/lifeline](https://github.com/avimehta30/lifeline)), included here as a submodule; its history holds the old file versions used by stale-output faults. |
| `env/facts.json` | Ground truth for the 13 hidden rules ("facts") in Lifeline, with the wrong version of each. Harness-only: agents never read it. |
| `env/seed_data.py` | Builds Lifeline's `data/` folder for a given seed. Harness-only. |
| `env/tasks/T01..T03/` | Tickets: `prompt.txt`, `starter.json` (Lifeline commit + seed), `meta.json`, `hidden_tests/`, `reference_solution/`, `wrong_fact_solutions/<fact>/`. Harness-only answer keys. |
| `harness/tasks.py`, `harness/grading.py` | Build a workspace from `starter.json`; grade it with the hidden tests (per-test results). |
| `tests/test_tasks.py` | Task sanity checks: starting code fails, reference passes, each wrong-fact solution fails (seeds 0–2). |
| `env/tools.py` | The only way agents touch the workspace: sandboxed tools, every call traced, blocked actions logged as unauthorized, one hook for harness faults. |
| `tracing/trace.py` | `trace.jsonl` events with `id` / `parent_ids` (the dependency graph). |
| `agents/` | `llm.py` (OpenAI-compatible client, UCSD TritonAI gateway by default, response cache), `base.py` (tool loop), researcher, planner, executor, orchestrator. |
| `harness/run_experiment.py` | Runs a task through the agents, grades it, writes `runs/<run>/trace.jsonl` and `metrics.json`. |
| `tests/test_lifeline.py` | Checks on the environment: Lifeline's own tests pass, module boundaries hold, each fact lives in exactly one file, seed data is reproducible. |

Still to build (see `CLAUDE.md`, "Build order"): tasks T04, T05 and T09–T11 (8 tasks in total; see `design.md` Section 5), the clean baseline, fault injection, recovery baselines, analysis.

## Setup

```bash
git clone --recurse-submodules https://github.com/avimehta30/Failure-Propagation-and-Recovery-in-Multi-Agent-Systems.git
# already cloned?  git submodule update --init
pip install -r requirements.txt
```

## Running the checks

```bash
python -m pytest                          # environment checks (includes Lifeline's own tests)
cd env/lifeline && python -m pytest       # Lifeline's own tests only
python -m env.seed_data /some/dir --seed 1   # data for another seed
python -m harness.run_experiment --task T01 --seed 0   # one clean run (OPENAI_BASE_URL and OPENAI_API_KEY from .env)
```
