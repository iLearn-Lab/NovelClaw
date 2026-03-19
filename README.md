# CoLong Idea Studio

<div align="center">

**Collaborative long-form story generation with dynamic memory, chapter planning, and an idea copilot.**

[Live Portal](https://colong-idea-studio.cloud) | [Project Page](https://xiao-zi-chen.github.io/CoLong-Idea-Studio/) | [Chinese Docs](README.zh-CN.md) | [Local Web Guide](RUN_LOCAL_WEB.md)

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/Web-FastAPI-009688)
![Vector DB](https://img.shields.io/badge/VectorDB-ChromaDB-orange)
![Mode](https://img.shields.io/badge/Mode-Dynamic%20Memory%20First-success)
![Workflow](https://img.shields.io/badge/Workflow-Chaptered%20Generation-purple)

</div>

`CoLong Idea Studio` is a memory-first agent framework for turning rough story ideas into long-form, chaptered output. Instead of generating everything in one shot, it keeps a working memory of outlines, summaries, characters, world settings, plot points, and fact cards, then re-injects that memory while later chapters are being written.

The project is built for people who want more than a one-pass "write me a novel" prompt. It helps you refine the idea first, plan chapters, write with stronger continuity, and inspect what the system is doing while it runs.

## Why It Stands Out

| Generic long-text generation | CoLong Idea Studio |
|---|---|
| Starts writing from a vague prompt | Uses an `Idea Copilot` loop to refine the premise before drafting |
| Context is mostly prompt-only | Writes back outlines, summaries, settings, and facts into dynamic memory |
| Later chapters often drift | Reuses typed memory to keep characters, setting, and plot commitments aligned |
| Hard to inspect mid-run | Exposes `progress.log`, chapter files, and memory artifacts during generation |

## Preview

<p align="center">
  <img src="docs/demo1.png" alt="CoLong dashboard preview" width="48%">
  <img src="docs/demo2.png" alt="CoLong job detail preview" width="48%">
</p>

## What You Can Do

- Refine a rough story idea with a collaborative `Idea Copilot` before formal writing starts.
- Generate chaptered long-form fiction with dynamic memory carried across chapters.
- Inspect outline creation, chapter planning, chapter-length targets, and memory writeback in `runs/<run_id>/progress.log`.
- Run the system from a CLI or a local multi-user FastAPI web portal.
- Keep each run's memory isolated under `vector_db/memory/run_<run_id>/`.

## Best For

- Long-form fiction and serialized stories
- Worldbuilding-heavy projects
- Human-in-the-loop co-writing workflows
- Experiments on memory-aware or agentic story generation

## Quick Start

### Option A: Local Web Portal

Recommended on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -r local_web_portal\requirements.txt
.\start_local.ps1
```

Open:

```text
http://127.0.0.1:8010
```

Why this path is recommended:

- It checks that your Python version is supported (`3.10+`).
- It validates that `local_web_portal.app.main:app` can be imported before startup.
- It avoids common issues caused by the wrong global Python or `uvicorn`.
- It disables embedding downloads by default during local startup.

Optional flags:

```powershell
.\start_local.ps1 -BindHost 0.0.0.0 -Port 8010
.\start_local.ps1 -Reload
```

### Option B: CLI

Create a root `.env` or export environment variables before running:

```text
LLM_API_KEY=your_api_key
LLM_PROVIDER=deepseek
MODEL_NAME=deepseek-chat
```

Accepted key aliases also include:

- `DEEPSEEK_API_KEY`
- `OPENAI_API_KEY`
- `CODEX_API_KEY`

Then run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

## How It Works

1. The user starts from a premise, setting, theme, or plot seed.
2. The `Idea Copilot Agent` keeps asking targeted questions until the idea is ready.
3. The system creates a global outline and chapter-level plans.
4. Each chapter is written with dynamic memory context assembled from recent summaries, fact cards, outlines, characters, and world settings.
5. New chapter summaries and fact cards are written back into memory for later chapters.
6. Runtime artifacts are saved so the process remains inspectable instead of opaque.

## Core Building Blocks

- `Collaborative ideation`: idea refinement is treated as an agent loop, not a shallow form helper.
- `Dynamic memory first`: the system prioritizes dynamic memory over static retrieval for long-form writing.
- `Typed memory assembly`: retrieved context is grouped by semantic role before prompt injection.
- `Progress-log observability`: planning, outline, length targets, memory snapshots, and chapter progress are visible while the job runs.

## Runtime Artifacts

These files are especially useful when debugging or inspecting a run:

```text
runs/<run_id>/progress.log
runs/<run_id>/output.txt
runs/<run_id>/chapters/
vector_db/memory/run_<run_id>/memory_index.json
```

Representative `progress.log` events:

| Event | Meaning |
|---|---|
| `global_outline` | Global outline persisted |
| `chapter_outline_ready` | Chapter outlines prepared |
| `chapter_plan` | Current chapter writing plan |
| `chapter_length_plan` | Chapter target and inferred source |
| `memory_snapshot` | Dynamic-memory snapshot |
| `character_setting` / `world_setting` | Setting memory written back |

## Architecture

![CoLong Idea Studio Workflow Diagram](docs/workflow-diagram-colong-idea-studio.png)

The workflow follows a closed loop of planning, writing, retrieval, storage, and reinjection so later chapters can stay aligned with earlier narrative commitments.

## Repository Layout

```text
.
|-- agents/                # writing, retrieval, and collaborative ideation agents
|-- workflow/              # analyzer / organizer / executor
|-- rag/                   # dynamic memory and retrieval logic
|-- utils/                 # LLM client and shared utilities
|-- local_web_portal/      # local multi-user FastAPI portal
|-- docs/                  # diagrams, screenshots, and project-page assets
|-- config.py              # configuration center
`-- main.py                # CLI entry
```

## Deployment Notes

- For deployment, prefer uploading source code and required docs only.
- Do not ship historical runtime data such as `runs/*`, `vector_db/*`, `.venv/*`, or `__pycache__/*`.
- Keep secrets in the real deployment environment instead of committing them.
- If you expose the portal publicly, put it behind HTTPS and a reverse proxy.

See [DEPLOY_WHITELIST.md](DEPLOY_WHITELIST.md) and [RUN_LOCAL_WEB.md](RUN_LOCAL_WEB.md) for operator-focused details.

## Documentation

- Chinese README: [README.zh-CN.md](README.zh-CN.md)
- Research-style project page: [xiao-zi-chen.github.io/CoLong-Idea-Studio](https://xiao-zi-chen.github.io/CoLong-Idea-Studio/)
- Local portal guide: [RUN_LOCAL_WEB.md](RUN_LOCAL_WEB.md)

## Citation

```bibtex
@software{colong_idea_studio_2026,
  title        = {CoLong Idea Studio: A Dynamic-Memory-First Collaborative Agent Framework for Long-Form Creative Ideation and Story Generation},
  author       = {xiao-zi-chen and contributors},
  year         = {2026},
  url          = {https://github.com/HITSZ-DS/CoLong-Idea-Studio}
}
```
