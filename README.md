# Failure Propagation and Recovery in Multi-Agent Systems

How does one agent's mistake spread through an AI team, and how can the team recover without redoing everything?

A three-agent team (**researcher → planner → executor**) works on tickets in **Lifeline**, a small made-up codebase for a fictional disaster-relief organization. We feed the team bad information at controlled points (fault injection), record every action together with what it was built from (a dependency graph), and measure how far the fault spreads and what recovery costs.

**Read first:** the report, [`report/main.pdf`](report/main.pdf) (18 pages, written for a general reader). Then [`CLAUDE.md`](CLAUDE.md) (how the experiment is built, and the rules) and [`design.md`](design.md) (Lifeline, its facts, and the tasks).

## Status

| Phase | State |
|---|---|
| **Phase 1**: clean baseline, fault injection, propagation, full-restart and always-verify baselines | **Done.** All runs complete; results below and in [`results/`](results/) |
| **Phase 2**: selective recovery (rerun only what the fault touched) | **Not started.** Do not build until the team agrees to begin |

Headline results (one model, `api-glm-5.3-flash`; 8 tasks × 3 seeds):

| | Result |
|---|---|
| Clean baseline | 20/24 runs pass; 0 unauthorized actions; about 57K tokens per run |
| Fault spread (accidental) | 20 of 69 runs: incorrect result 12/30, stale output 5/15, timeout 3/24 |
| Fault spread (adversarial) | 0 of 12: plainly worded planted instructions were never followed |
| Full restart | 53/69 tasks recovered, but texts and payments sent by mistake rose from 22 to **76** (a restart repeats them) |
| Always-verify | 53/69 recovered, **0** bad sends, but 2.3× the tokens and 16 false alarms |

Full tables: [`results/summary.md`](results/summary.md) (CSV versions alongside).

**Known open issues** (good first discussions):
- T11 fails even with no fault: the audit rule lives only in `audit/log.py` and no agent finds it.
- The adversarial tests use only blunt comments; disguised instructions and a compromised planner → executor message are untested.
- Fact F3 is used by no task (its task was dropped when we cut from 12 to 8).

## Quickstart (5 minutes, no API key needed)

```bash
git clone --recurse-submodules https://github.com/avimehta30/Failure-Propagation-and-Recovery-in-Multi-Agent-Systems.git
cd Failure-Propagation-and-Recovery-in-Multi-Agent-Systems
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest     # 169 checks, no model calls
```

Both repositories are private: you need access to this one **and** to [avimehta30/lifeline](https://github.com/avimehta30/lifeline) (the submodule), or the clone stops partway. Already cloned without the submodule? Run `git submodule update --init`.

**Replay a real run for free.** Every model reply is cached in `runs/.llm_cache/` (tracked in git), so rerunning an experiment with the same settings replays the same replies, with no key, no cost and identical results:

```bash
python -m harness.run_experiment --task T01 --seed 0    # replays from the cache in seconds
cat runs/T01__clean__s0/metrics.json                      # grade, tokens, latency
head -5 runs/T01__clean__s0/trace.jsonl                   # events with id and parent_ids
```

**Rebuild all results.** These replay from the cache too: a fresh clone with no key reproduces every table in `results/` exactly, except the latency columns, which measure the replay (about a second) rather than the original model time. Only runs whose prompts or settings changed call the model. Keep runs inside the repo's `runs/` folder; the cache matches prompts by their paths relative to the repo.

```bash
python -m harness.run_grid clean      # 24 clean runs        -> runs/baseline/
python -m harness.run_grid faults     # 81 fault runs        -> runs/faults/
python -m harness.run_grid restart    # full restart         -> runs/recovery/
python -m harness.run_grid verify     # always-verify        -> runs/recovery/
python -m analysis.summarize          # tables               -> results/
```

The original traces and metrics of every run are attached to the [GitHub release](https://github.com/avimehta30/Failure-Propagation-and-Recovery-in-Multi-Agent-Systems/releases) as a zip, if you want to read them without rerunning.

**New model calls** (new runs, changed prompts) need a key: `cp .env.example .env` and add your own UCSD TritonAI key. Each person uses their own key. Never commit `.env`.

## How a run works

1. The harness builds a fresh copy of Lifeline in `runs/<run>/workspace/` at the task's starting commit and seed.
2. The **researcher** reads the code (read-only tools) and reports separate findings (`R1`, `R2`, ...).
3. The **planner** (no tools) writes one step per file, citing the findings it uses (`P1: ... uses R1, R2`).
4. The **executor** edits files, or writes and runs a script for operations tasks, one traced edit per plan step.
5. If configured, the harness injects a fault on the way (it changes only what an agent *sees*, never files on disk).
6. The harness grades the result with hidden tests (code tasks) or an expected final state (operations tasks), then writes `trace.jsonl` and `metrics.json`.

## Repository map

| Path | What it is |
|---|---|
| `report/` | The Phase 1 report (`main.tex`, `main.pdf`). Build with `tectonic main.tex` |
| `results/` | Summary tables from `analysis/summarize.py` |
| `env/lifeline/` | **Lifeline** (submodule, its own repo). 19 Python files, its own tests, seed data. Its Git history holds the old versions used by stale-output faults |
| `env/facts.json` | The 13 hidden rules ("facts") and their plausible wrong versions. Harness only |
| `env/tasks/T01..T11/` | 8 tickets: `prompt.txt` (all the agents see), `starter.json`, `meta.json`, and answer keys (`hidden_tests/` or `expected_state/`, `reference_solution/`, `wrong_fact_solutions/`) |
| `env/tools.py` | The only way agents touch the workspace: sandboxed tools, every call traced, forbidden actions blocked and logged, one hook for faults |
| `env/seed_data.py` | Builds Lifeline's data for a seed |
| `agents/` | `llm.py` (OpenAI-compatible client and cache), `base.py` (tool loop), researcher, planner, executor, verifier, orchestrator |
| `tracing/trace.py` | `trace.jsonl` events with `id` and `parent_ids` (the dependency graph) |
| `harness/` | `run_experiment.py` (one run), `run_grid.py` (batches), `faults.py`, `propagation.py`, `recovery.py`, `ops.py` (operations-task grading), `configs/phase1.yaml` |
| `analysis/summarize.py` | Aggregates `runs/` into `results/` |
| `tests/` | 169 model-free checks: environment, answer keys, sandbox, tracing, pipeline, faults, recovery |
| `runs/` | Run output (gitignored), except `runs/.llm_cache/`, which is tracked |

## Rules for contributors

The full list is in [`CLAUDE.md`](CLAUDE.md) under "Hard rules". The ones that matter most day to day:

- **Never change the answer keys or tests to make a run pass.** Agents are not allowed to add or edit tests either; the evaluation must stay fixed.
- **Agents touch the environment only through `env/tools.py`**, and can never read answer keys or `facts.json`.
- **Agent code contains no fault logic.** Faults come only from `harness/faults.py`, and never modify files on disk.
- **Everything is traced** with `id` and `parent_ids`; do not merge findings, plan steps or edits into one item.
- **Runs must be reproducible:** temperature 0, fixed seeds, config-driven, cached replies. If you change a prompt, the cache misses and the model is called again; say so in your PR.
- **No secrets in git.** Each person keeps their own key in `.env`.
- Ask the team before adding a dependency or starting Phase 2.

Working on the code: make small changes, run `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest` (the variable avoids a clash with unrelated pytest plugins some machines have installed), and open a pull request against `main`.
