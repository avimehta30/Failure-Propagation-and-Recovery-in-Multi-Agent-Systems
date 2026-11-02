# Failure-Propagation-and-Recovery-in-Multi-Agent-Systems
Measuring how faults spread through a researcher → planner → executor agent team working on a codebase, and how the team can recover without redoing all its work.

**Status: Phase 1, building the environment.** See `CLAUDE.md` for how the experiment is built and `design.md` for the environment and tasks.

## Layout

| Path | What it is |
|---|---|
| `env/lifeline/` | **Lifeline**, a fictional disaster-relief codebase the agents work on (about 20 small Python files, its own tests, seed data in `data/`). It is its own Git repo ([avimehta30/lifeline](https://github.com/avimehta30/lifeline)), included here as a submodule; its history holds the old file versions used by stale-output faults. |
| `env/facts.json` | Ground truth for the 13 hidden rules ("facts") in Lifeline, with the wrong version of each. Harness-only: agents never read it. |
| `env/seed_data.py` | Builds Lifeline's `data/` folder for a given seed. Harness-only. |
| `tests/test_lifeline.py` | Checks on the environment: Lifeline's own tests pass, module boundaries hold, each fact lives in exactly one file, seed data is reproducible. |

Still to build (see `CLAUDE.md`, "Build order"): tasks T01–T12, sandboxed tools, tracing, agents, fault-injection harness, recovery baselines, analysis.

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
```
