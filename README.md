# PresentationAgent - The AI Workspace for Research-First Presentation Creation

![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![Next.js 15](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white)
![React 19](https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white)
![WebDeck Runtime](https://img.shields.io/badge/WebDeck-Runtime-111827)
![Local-first](https://img.shields.io/badge/Deployment-Local--first-0F766E)

English | [简体中文](./README_CN.md)

> Turn a brief, a set of files, or a URL into a reviewable WebDeck, editable diagrams, and exportable presentation assets.
> PresentationAgent combines conversational creation, evidence-first planning, WebDeck page orchestration, a diagram-first draw.io workspace, asset management, and gallery publishing in a single locally deployable platform.

`Research-first` · `WebDeck Runtime` · `Diagram-first` · `Gallery & Remix` · `Packages & Skills`

## Why PresentationAgent

Most AI presentation tools stop at “prompt in, slides out.” PresentationAgent is built more like a production workspace for decks:

- **Research before rendering**: attachments, URLs, and context flow through a briefing / evidence stage before planning and page generation.
- **Not a single-thread slide generator**: the WebDeck runtime respects page dependencies, supports lane-level logs, retries failed pages, and performs deck-level review.
- **Diagrams are first-class**: draw.io runs as a diagram-first workflow with autosave, validation, and restore around a persistent diagram session.
- **Artifacts have a lifecycle**: upload files, save outputs as assets, publish to the gallery, fork / remix, and extend the platform with packages and skills.
- **Deploy locally**: frontend and backend run on your machine; data stays in local SQLite and the filesystem by default, while external calls are limited to the model and APIs you configure.

| Capability | PresentationAgent | Template fillers | One-shot chat export |
|---|---|---|---|
| Research-first planning from source material | ✅ | ⚠️ | ❌ |
| Page-level concurrent generation and retry | ✅ | ❌ | ❌ |
| WebDeck preview and ongoing editing | ✅ | ⚠️ | ❌ |
| Diagram-first draw.io workflow | ✅ | ❌ | ❌ |
| Assets / gallery / fork / remix | ✅ | ❌ | ❌ |
| Package / skill extensibility | ✅ | ❌ | ❌ |

## Interface Preview

![Presentation workspace](assets/%E6%BC%94%E7%A4%BA%E6%96%87%E7%A8%BF%E5%B7%A5%E4%BD%9C%E5%8F%B0%E9%A1%B5%E9%9D%A2.png)
![Presentation outline preview](assets/%E6%BC%94%E7%A4%BA%E6%96%87%E7%A8%BF%E5%A4%A7%E7%BA%B2%E9%A2%84%E8%A7%88%E9%A1%B5%E9%9D%A2.png)
![Draw.io workspace](assets/draw.io%E5%B7%A5%E4%BD%9C%E5%8F%B0%E9%A1%B5%E9%9D%A2.png)
![Web sandbox preview](assets/web%E6%B2%99%E7%9B%92%E9%A2%84%E8%A7%88%E9%A1%B5%E9%9D%A2.png)
![Smart document workspace](assets/%E6%99%BA%E8%83%BD%E6%96%87%E6%A1%A3%E9%A1%B5%E9%9D%A2.png)

## Sample Output

[AI Development Status and Trend Analysis.pptx](assets/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD%E5%8F%91%E5%B1%95%E7%8E%B0%E7%8A%B6%E4%B8%8E%E8%B6%8B%E5%8A%BF%E5%88%86%E6%9E%90.pptx)

## Core Capabilities

- **Conversational WebDeck creation**: start from a brief, audience, page count, and style constraints, generate a structured brief / manifest first, then move into page generation.
- **Evidence-first orchestration**: PDFs, DOCX, PPTX, Markdown, images, and URLs are parsed into evidence and context layers before generation, reducing “make it up from the prompt” behavior.
- **Dependency-aware parallel generation**: independent pages can run concurrently, with the current scheduler defaulting to 20 as the max page concurrency; dependent pages wait when they should, and failed pages or failed lanes can be retried directly.
- **Mandatory review and observability**: page-level and deck-level review are part of the workflow, with visible TOC, lane status, failure reasons, and retry feedback instead of a black-box final file.
- **WebDeck editing and rollback**: browse the deck via TOC, inspect the current page, save manual edits, inspect page versions, roll back, and republish the full deck.
- **Diagram-first draw.io workspace**: create, edit, autosave, validate, and restore diagrams while keeping AI edits anchored to the latest diagram session, not stale chat output.
- **Multi-artifact workspace**: the same workspace can host `ppt`, `webdeck`, `drawio`, `document`, `code`, and `webpage` artifacts.
- **Assets, gallery, and extension surface**: outputs can be saved as assets, published to the gallery, forked or remixed by others, and extended through the package registry or remote package import.

## Typical Workflow

1. Upload PDFs, DOCX, PPTX, Markdown, images, or paste raw text and URLs.
2. Describe the audience, use case, page count, style, and key conclusions in natural language.
3. Confirm the generated brief / outline / manifest.
4. Let the WebDeck runtime generate pages in parallel and retry weak or failed pages in a targeted way.
5. Refine the result manually in the WebDeck or draw.io workspace.
6. Save the result as an asset, publish it to the gallery, or export HTML / PDF / PPTX variants.

```text
You: Build a 10-slide AI Agent architecture deck from this industry research PDF
and the two attached charts. Audience: CTOs and product leads. Style: technical launch keynote.

AI: I will first extract the evidence, prepare a WebDeck brief for your review,
then generate the deck page-by-page and return an editable workspace plus export options.
```

## Quick Start

### 1. Prerequisites

| Dependency | Required? | Purpose |
|---|:---:|---|
| Python 3.12+ | ✅ | Backend runtime and agent / tool services |
| Node.js 18+ | ✅ | Next.js frontend |
| npm 9+ | ✅ | Frontend dependency installation |
| `LLM_API_KEY` | ✅ | Access to your chosen model provider |
| Playwright Chromium | Recommended | PDF and `pptx-faithful` export |

> **TL;DR**: configure `.env`, create a local virtual environment, run `pip install -r requirements.txt`, install frontend dependencies, then start backend and frontend.

### 2. Clone and configure the project

```bash
git clone https://github.com/GX-Alex/presentation-ppt-agent.git
cd presentation-ppt-agent
cp .env.example .env
```

Edit `.env` and set at least:

```bash
LLM_API_KEY=your-api-key
LLM_MODEL=deepseek/deepseek-chat
```

### 3. Create a virtual environment and install backend dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

> If you only want to get chat, WebDeck, draw.io, and HTML preview running, you can skip `python -m playwright install chromium` for now. PDF and `pptx-faithful` export will be unavailable until you install it.

<details>
<summary><strong>Windows PowerShell</strong></summary>

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```
</details>

### 4. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 5. Start the backend

```bash
source .venv/bin/activate
cd backend
python main.py
```

The default local backend address is `http://localhost:8002`.

### 6. Start the frontend

Open a second terminal:

```bash
cd frontend
npm run dev
```

Open:

- Frontend: `http://localhost:3000`
- Backend health: `http://localhost:8002/api/health`

If you move the backend to another port, start the frontend with an explicit `BACKEND_URL`:

```bash
cd frontend
BACKEND_URL=http://localhost:8012 npm run dev
```

## Key Configuration

| Environment variable | Required? | Default | Purpose |
|---|:---:|---|---|
| `LLM_API_KEY` | ✅ | - | Primary model API key |
| `LLM_MODEL` | No | `deepseek/deepseek-chat` | Default model |
| `DATABASE_URL` | No | Local SQLite | Database storage |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Allowed frontend origins |
| `PEXELS_API_KEY` | No | - | Better image search |
| `TAVILY_API_KEY` | No | - | Better web research |

## Current Focus

> The primary path today is **WebDeck generation + diagram-first editing + asset / gallery workflows**.
> The repo still contains some historical PPT-only routes and compatibility APIs, but the product direction is converging on a unified web-native deck runtime.

## Tech Stack

| Layer | Stack |
|---|---|
| Frontend | Next.js 15, React 19, TypeScript, Tailwind, Zustand |
| Backend | FastAPI, SQLAlchemy asyncio, aiosqlite |
| Model access | LiteLLM |
| Workflow runtime | WebSocket + REST, task-scoped agent loop, WebDeck runtime |
| Document parsing | PyMuPDF, python-docx, python-pptx, openpyxl |
| Diagram / visual layer | Draw.io, SVG, HTML-based chart lanes |
| Export | HTML, PDF, PPTX faithful, PPTX editable |
| Persistence | SQLite + local filesystem |

## Project Layout

```text
presentation-ppt-agent/
├── backend/
│   ├── app/api/                  # files / gallery / packages / presentations / webdeck ...
│   ├── app/core/                 # agent loop, LLM client, tool dispatch
│   ├── app/tools/                # parse_document, edit_diagram, web_search, retry_failed_deck_pages ...
│   ├── app/services/
│   │   ├── webdeck_runtime/      # director, planner, scheduler, reviewer, publish
│   │   ├── browser_pool.py       # Playwright-backed export capability
│   │   ├── export_service.py     # HTML / PDF / PPTX export
│   │   └── package_registry.py   # package / workflow extension surface
│   └── main.py
├── frontend/
│   ├── src/components/chat/      # chat and streaming feedback
│   ├── src/components/webdeck/   # WebDeck preview and editing
│   ├── src/components/drawio/    # diagram workspace
│   ├── src/components/workspace/ # multi-artifact workspace shell
│   └── src/components/packages/  # package registry UI
├── docs/plans/                   # implementation and evolution plans
├── .env.example
├── requirements.txt              # root-level backend dependency entrypoint
├── README.md
└── README_CN.md
```

## Roadmap

- Richer WebDeck hybrid editing with finer page-level control
- A stronger public gallery and collaboration layer
- More reliable export adapters and publishing flows
- Better package / skill distribution for reusable workflows
- More complete public documentation and example projects

## Feedback

Use it on real presentation, research, architecture, and diagram collaboration work.
If it helps, give it a Star after the public launch and share issues or improvements through Issues and PRs.