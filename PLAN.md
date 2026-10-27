# Boots Bundle Image Studio — Comprehensive Build Plan

**Status:** DRAFT — Awaiting User Approval  
**Date:** October 27, 2026  
**Author:** Faizan Naveed, Digital Services Assistant, Product Enrichment

---

## 1. Executive Summary

Build a standalone web application — not a Writer playbook, not an HTML file — that functions as complete software. It will live on a private GitHub repository, be developed in VS Code (with AI coding assistant as an optional AI coding assistant), deploy the backend to Render and the frontend to Vercel, and use GitHub Actions for CI/CD. The app uses Google Gemini API (Nano Banana 2.1) for AI image editing and Python PIL for deterministic product compositing with 100% fidelity.

### Why a standalone app (not Writer playbooks)

| Problem in Writer | Why it's unfixable | How the app solves it |
|---|---|---|
| `generate_image` alters colours, artwork, text, proportions | AI generates from scratch; no prompt rule can prevent this | PIL places actual product photos — pixel-perfect fidelity |
| Editing takes 30 minutes | Base64 data URI passed as inline text, too large for agent context | Direct file handling — images are files, not text strings |
| Dashboard blank | CSP blocks external fonts; string replacement collision in template | Full React app with proper bundler, no CSP workarounds |
| Edit button breaks on download | `/_gateway/` paths only exist on Writer proxy | Backend API is a real server — works from anywhere |
| Monday.com MCP not accessible by child agents | Platform-level connector access issue | Direct Monday.com API calls — no MCP dependency |

---

## 2. Technology Stack

### Backend (Python)
- **Framework:** FastAPI (async, fast, auto-generates OpenAPI docs)
- **Server:** Uvicorn (ASGI), bound to `0.0.0.0:$PORT` for Render
- **Image Processing:** Pillow (PIL) — deterministic product compositing
- **AI Image Editing:** Google Gemini API via `google-genai` Python SDK
- **HTTP Client:** httpx (async) — for Monday.com API + Boots.com crawling
- **Excel Parsing:** openpyxl — for Monday.com file downloads (.xlsx)
- **File Handling:** python-multipart — for image upload/download endpoints
- **Environment:** python-dotenv — local `.env` file loading

### Frontend (React)
- **Framework:** React 18+ with Vite (fast build, no CRA bloat)
- **Language:** JavaScript (can upgrade to TypeScript later if desired)
- **HTTP Client:** fetch API (no extra dependency needed)
- **Styling:** CSS modules or Tailwind CSS (to be decided)
- **State Management:** React hooks (useState/useReducer) — no Redux needed

### Infrastructure
- **Repository:** Private GitHub repository
- **Backend Hosting:** Render (Web Service, Python runtime)
- **Frontend Hosting:** Vercel (static site, auto-deploy from GitHub)
- **CI/CD:** GitHub Actions (separate workflows for backend + frontend)
- **Development:** VS Code with AI coding assistant extension (optional AI assistant)
- **Containerization:** Dockerfile for backend (optional, Render supports native Python)

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────┐
│                    User's Browser                     │
│                   (React Frontend)                    │
│  Dashboard · Approve · Edit · Export · 3 Tabs         │
└──────────────────────┬──────────────────────────────┘
                       │ HTTPS REST API
                       ▼
┌─────────────────────────────────────────────────────┐
│              Render Backend (FastAPI)                 │
│                                                       │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ Monday   │  │ Image        │  │ Gemini Client  │ │
│  │ Client   │  │ Composer     │  │ (Nano Banana)  │ │
│  │          │  │ (PIL)        │  │                │ │
│  └────┬─────┘  └──────┬───────┘  └───────┬────────┘ │
│       │               │                  │           │
│       ▼               ▼                  ▼           │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ Boots    │  │ Bundle       │  │ Google Gemini  │ │
│  │ Crawler  │  │ Processor    │  │ API            │ │
│  └──────────┘  └──────────────┘  └────────────────┘ │
└─────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
   Monday.com API      Boots.com (with x-agent-client bypass)
```

### Data Flow

1. **Fetch bundles:** Frontend → `GET /api/bundles` → Monday.com API (Core Line List + 2am Report) → identify Virtual Bundles, cross-reference live status → Boots.com crawler (download current bundle images + individual product images) → Bundle Processor (quality assessment, categorize into ready/supplier/manual) → return JSON to frontend

2. **Generate bundle image:** Frontend → `POST /api/generate` → Image Composer (PIL: place product photos on 2000×2000 white canvas with gaps, shadows, roundel) → return composed image

3. **Edit bundle image:** Frontend → `POST /api/edit` (with image + prompt) → try programmatic edit first (gap/size/center adjustments via PIL) → if prompt needs AI → Gemini API (Nano Banana 2.1, image-to-image editing with reference images) → return edited image

4. **Approve:** Frontend → `POST /api/approve` → mark bundle as approved (store in memory or file)

5. **Export:** Frontend → `GET /api/export` → package all approved images as ZIP with correct 8-digit Boots bundle codes as filenames

---

## 4. Repository Structure

```
boots-bundle-studio/          # Private GitHub repository
├── .github/
│   └── workflows/
│       ├── backend-ci.yml       # Lint + test backend on PR
│       ├── backend-deploy.yml   # Deploy backend to Render on main push
│       ├── frontend-ci.yml      # Lint + build frontend on PR
│       └── frontend-deploy.yml  # Deploy frontend to Vercel on main push
├── backend/
│   ├── requirements.txt
│   ├── Dockerfile               # Optional: for Docker-based deploy
│   ├── app.py                   # FastAPI server + all REST endpoints
│   ├── monday_client.py         # Monday.com API client
│   ├── boots_crawler.py         # Boots.com crawler (x-agent-client bypass)
│   ├── image_composer.py        # PIL compositing (deterministic, 100% fidelity)
│   ├── gemini_client.py         # Google Gemini API integration
│   ├── bundle_processor.py      # Quality assessment + categorization
│   ├── roundel.png              # Roundel overlay for 6+ identical items
│   └── uploads/                 # Temporary image storage (gitignored)
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   ├── src/
│   │   ├── main.jsx
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── Dashboard.jsx
│   │   │   ├── BundleCard.jsx
│   │   │   ├── EditPanel.jsx
│   │   │   ├── TabBar.jsx
│   │   │   └── ExportButton.jsx
│   │   ├── api/
│   │   │   └── client.js        # API call functions
│   │   └── styles/
│   │       └── dashboard.css
│   └── public/
├── .gitignore
├── .env.example
├── render.yaml                  # Render Blueprint (Infrastructure as Code)
├── vercel.json                  # Vercel config (frontend)
├── README.md
└── PLAN.md                      # This document
```

---

## 5. Backend — Detailed Design

### 5.1 Module: `monday_client.py` (✅ Already written)
- `MondayClient` class
- Fetches Core Line List and 2am Report from Monday.com board
- Parses Core Line List to identify Virtual Bundles (product codes, quantities, titles)
- Parses 2am Report to determine which bundles are actually live
- Cross-references to produce confirmed live bundles list
- Direct GraphQL API calls — no MCP connector dependency

### 5.2 Module: `boots_crawler.py` (✅ Already written)
- `BootsCrawler` class
- Searches Boots.com for a specific bundle by product code
- Downloads the current bundle image (the one we're evaluating for quality)
- Extracts and downloads individual product images from the bundle page
- Uses `x-agent-client=W-7njoVr89mFAk` query parameter bypass for Imperva/Incapsula

### 5.3 Module: `image_composer.py` (✅ Already written)
- `ImageComposer` class
- Creates 2000×2000 white canvas
- Places actual product photos with preserved aspect ratios
- Visible gaps between products (NO overlap) — default 60px
- Subtle realistic contact shadows (elliptical, blurred)
- Roundel overlay for 6+ identical items
- Auto-scales products if total width exceeds canvas
- `compose_bundle_image()` — primary generation method
- `edit_bundle_image()` — programmatic edits (gap, size, center adjustments)
- `compose_from_product_images()` — compose from individual product photos + quantities

### 5.4 Module: `gemini_client.py` (⬜ To be written)
- `GeminiClient` class
- Uses `google-genai` Python SDK
- **Model:** `gemini-nano-banana-2.1` (recommended for new projects per Google docs)
  - Note: `gemini-2.5-flash-image` (original Nano Banana) being retired Oct 2, 2026
- **Capabilities:**
  - `edit_image(image_path, prompt, reference_images=None)` — image-to-image editing
  - `edit_with_references(image_path, prompt, reference_paths)` — multi-reference editing
  - `generate_from_prompt(prompt)` — text-to-image (fallback when no product images available)
- **Strict product fidelity instructions** baked into every prompt:
  - Preserve original packaging, colours, labels, logos, text, branding
  - Do not redesign, redraw, or reinterpret products
  - Do not stretch, compress, or distort
  - Use reference images as visual ground truth
- **Error handling:** Retry up to 3 times on failure, return meaningful error to frontend
- **Fallback:** If Gemini edit fails or alters product fidelity, flag for manual review

### 5.5 Module: `bundle_processor.py` (⬜ To be written)
- `BundleProcessor` class
- **Quality assessment:** Evaluate current Boots.com bundle image quality
  - Check: Are products touching/overlapping?
  - Check: Are colours accurate (compare to individual product photos)?
  - Check: Is background clean white?
  - Check: Are all labels/text legible?
  - Check: Are product proportions correct?
- **Categorization logic:**
  - `ready` — Good quality image, or we've generated a better one → Ready for Approval
  - `supplier` — No suitable individual product images found → Supplier Image Required
  - `manual` — Can't confidently compose or quality issues → Manual Review Required
- **Arrangement rules (from requirements doc):**
  - Fewer than 4 products: Arrange all in one image
  - 4+ products: Evaluate sizes, quantities, packaging shapes, available space
  - If composition can't be determined confidently → Manual Review
- Returns structured JSON for the frontend

### 5.6 Module: `app.py` — FastAPI Server (⬜ To be written)
- **CORS middleware:** Allow Vercel frontend origin
- **Health checks:** `GET /healthz` (liveness), `GET /readyz` (readiness) — required by Render
- **Static file serving:** Serve generated images from `/uploads/`
- **Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/healthz` | Liveness check (always returns 200) |
| `GET` | `/readyz` | Readiness check (verifies Monday.com + Gemini keys loaded) |
| `GET` | `/api/bundles` | Fetch all bundles from Monday.com, crawl Boots.com, categorize |
| `POST` | `/api/generate` | Compose a bundle image from product photos (PIL) |
| `POST` | `/api/edit` | Edit a bundle image (programmatic first, Gemini fallback) |
| `POST` | `/api/approve` | Mark a bundle image as approved |
| `POST` | `/api/reject` | Mark a bundle image as rejected (back to manual review) |
| `GET` | `/api/export` | Export all approved images as ZIP (8-digit bundle codes as filenames) |
| `GET` | `/api/bundle/{code}` | Get details for a specific bundle |
| `POST` | `/api/upload` | Upload a supplier-provided image for a bundle |

- **Render configuration:**
  - Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
  - Build command: `pip install -r requirements.txt`
  - Health check path: `/healthz`

---

## 6. Frontend — Detailed Design

### 6.1 Component Architecture

```
App.jsx
├── TabBar.jsx              # 3 tabs: Ready / Supplier / Manual
├── Dashboard.jsx
│   ├── BundleCard.jsx      # One per bundle
│   │   ├── Side-by-side: Original (Boots.com) vs Generated
│   │   ├── Approve Button
│   │   ├── Edit Button → opens EditPanel
│   │   └── Status badge
│   └── EditPanel.jsx       # Slide-in panel
│       ├── Current image preview
│       ├── Prompt input (natural language)
│       ├── Regenerate button
│       ├── Loading state
│       ├── Error display
│       └── Compare original vs edited
└── ExportButton.jsx        # Export approved as ZIP
```

### 6.2 Key Features
- **3 dashboard tabs:** Ready for Approval, Supplier Image Required, Manual Review Required
- **Side-by-side display:** Original Boots.com image vs. Generated/composed image
- **Approve/Reject:** Mark images as approved or send back to manual review
- **Edit panel:** Natural language prompt → backend → PIL (programmatic) or Gemini (AI) → display result
- **Multi-round editing:** User can refine prompt and regenerate repeatedly
- **Export:** Download all approved images as ZIP with correct 8-digit bundle codes
- **Error handling:** Meaningful error messages, retry option on failure
- **Responsive design:** Works on desktop (primary use case)

### 6.3 API Client (`api/client.js`)
- All REST calls go through the backend API
- Base URL configurable via environment variable (`VITE_API_URL`)
- Handles loading states and error responses

---

## 7. Deployment Plan

### 7.1 Backend → Render

**Method:** Render Web Service (native Python runtime)

**Configuration (`render.yaml` Blueprint):**
```yaml
services:
  - type: web
    name: boots-bundle-studio-api
    runtime: python
    region: frankfurt          # Closest to UK
    plan: starter              # $7/mo — sufficient for internal tool
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /healthz
    envVars:
      - key: GEMINI_API_KEY
        sync: false            # Set in Render dashboard (secret)
      - key: MONDAY_API_TOKEN
        sync: false
      - key: MONDAY_BOARD_ID
        value: "5100428483"
      - key: BOOTS_X_AGENT_CLIENT
        value: "W-7njoVr89mFAk"
      - key: CORS_ORIGINS
        sync: false            # Set to Vercel frontend URL after first deploy
```

**Key requirements (from Render docs):**
- Must bind to `0.0.0.0:$PORT` (Render sets PORT env var)
- Use `uvicorn` directly (not `fastapi dev`)
- Health check at `/healthz` for zero-downtime deploys
- Environment variables set in dashboard, never committed

**Steps:**
1. Create Render account (if not already)
2. New Web Service → connect GitHub repo
3. Set build/start commands
4. Add environment variables (GEMINI_API_KEY, MONDAY_API_TOKEN, etc.)
5. Deploy — Render builds and starts automatically
6. Note the backend URL (`https://boots-bundle-studio-api.onrender.com`)
7. Set CORS_ORIGINS to the Vercel frontend URL (after frontend deploy)

### 7.2 Frontend → Vercel

**Method:** Vercel static site with GitHub Actions CI/CD

**Why GitHub Actions (not Vercel's built-in Git integration):**
- Private repository on Vercel Hobby plan requires GitHub Actions
- `vercel build` + `vercel deploy --prebuilt` keeps source code private
- Separate preview (non-main branches) and production (main branch) workflows

**Configuration (`vercel.json`):**
```json
{
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "framework": "vite"
}
```

**Required GitHub Secrets:**
- `VERCEL_TOKEN` — Vercel API token
- `VERCEL_ORG_ID` — Vercel organization ID
- `VERCEL_PROJECT_ID` — Vercel project ID

**Steps:**
1. Create Vercel account (if not already)
2. `vercel link` in the frontend directory to create a project
3. Save `projectId` and `orgId` from `.vercel/project.json`
4. Add as GitHub secrets: `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`
5. Set `VITE_API_URL` environment variable in Vercel (point to Render backend URL)
6. GitHub Actions deploys automatically on push to main

---

## 8. CI/CD Pipeline

### 8.1 Backend CI (`backend-ci.yml`)
**Trigger:** Pull request to main
**Steps:**
1. Checkout code
2. Set up Python 3.12
3. Install dependencies
4. Run `ruff check .` (linting)
5. Run `pytest` (unit tests — if any)
6. Build Docker image (syntax check, not deployed)

### 8.2 Backend Deploy (`backend-deploy.yml`)
**Trigger:** Push to main branch
**Steps:**
1. Run CI checks (lint + test)
2. Trigger Render Deploy Hook via curl
3. Render pulls latest code and redeploys

**Required GitHub Secret:** `RENDER_DEPLOY_HOOK`

### 8.3 Frontend CI (`frontend-ci.yml`)
**Trigger:** Pull request to main
**Steps:**
1. Checkout code
2. Set up Node.js 20
3. `npm ci` (clean install)
4. `npm run lint` (if configured)
5. `npm run build` (verify build succeeds)

### 8.4 Frontend Deploy (`frontend-deploy.yml`)
**Trigger:** Push to main branch
**Steps:**
1. Checkout code
2. Set up Node.js 20
3. Install Vercel CLI
4. `vercel pull --yes --environment=production --token=$VERCEL_TOKEN`
5. `vercel build --prod --token=$VERCEL_TOKEN`
6. `vercel deploy --prebuilt --prod --token=$VERCEL_TOKEN`

---

## 9. Security Plan

### 9.1 Repository Security
- **Private GitHub repository** — only invited collaborators can see code
- **No secrets in code** — all API keys via environment variables
- **`.env` gitignored** — `.env.example` with placeholder values only
- **Dependabot enabled** — automatic security vulnerability alerts
- **Branch protection** — require PR review before merging to main
- **Minimal GitHub Actions permissions** — `permissions: contents: read` by default

### 9.2 API Security
- **CORS restricted** — only allow Vercel frontend origin, not `*`
- **API key validation** — backend checks for valid Gemini + Monday.com keys on startup
- **Rate limiting** — prevent abuse (optional, can add with `slowapi` library)
- **Input validation** — Pydantic models for all request bodies
- **File upload validation** — check file type (images only), max size limit
- **No sensitive data in responses** — API keys never returned to frontend

### 9.3 Secret Management
- **Render:** Environment variables set in dashboard, encrypted at rest
- **Vercel:** Environment variables set in project settings
- **GitHub:** Secrets stored encrypted, masked in logs
- **Local dev:** `.env` file (gitignored), never committed

### 9.4 Network Security
- **HTTPS only** — both Render and Vercel enforce HTTPS by default
- **Boots.com crawling:** Uses `x-agent-client` bypass (already verified working)
- **Monday.com API:** Uses official GraphQL API with token auth
- **Gemini API:** Uses Google's official SDK with API key auth

---

## 10. VS Code + AI coding assistant Development Workflow

### 10.1 VS Code Setup
1. Install VS Code
2. Install Python extension (Microsoft)
3. Install ESLint extension (for frontend)
4. Install Pylance extension (Python type checking)
5. Install GitHub Pull Requests extension
6. Optional: Install AI coding assistant extension

### 10.2 AI coding assistant Integration
AI coding assistant is an AI coding assistant that works directly in VS Code. It can:
- Read and understand the entire codebase
- Write and edit code across multiple files
- Run terminal commands
- Create git commits
- Help debug issues

**How to use:**
1. Install AI coding assistant VS Code extension
2. Open the `boots-bundle-studio` folder in VS Code
3. Use AI coding assistant to:
   - Write new modules (e.g., "Write the Gemini client module following the plan")
   - Debug issues (e.g., "The /api/edit endpoint returns 500, find the bug")
   - Write tests (e.g., "Write unit tests for image_composer.py")
   - Refactor code (e.g., "Add error handling to all API endpoints")
   - Generate documentation

### 10.3 Development Workflow
```
Local Dev (VS Code)
    │
    ├── Edit code (with AI coding assistant assistance)
    ├── Test locally (uvicorn + vite dev server)
    ├── Git commit
    ├── Push to GitHub (feature branch)
    │
    ▼
GitHub (Private Repo)
    │
    ├── Pull Request → CI runs (lint, test, build check)
    ├── Review → Merge to main
    │
    ▼
Main Branch
    │
    ├── GitHub Actions: Backend deploy → Render
    ├── GitHub Actions: Frontend deploy → Vercel
    │
    ▼
Live Application
    ├── Backend: https://boots-bundle-studio-api.onrender.com
    └── Frontend: https://boots-bundle-studio.vercel.app
```

---

## 11. Gemini API Integration Details

### 11.1 Model Selection
- **Primary:** `gemini-nano-banana-2.1` — recommended for all new projects
  - High-efficiency workhorse, Flash-level speed
  - Improved visual quality, text rendering, multi-turn consistency
  - Supports 1K, 2K, 4K resolutions
- **Fallback:** `gemini-3.1-flash-lite-image` — fastest/cheapest, for simple edits
- **Premium (if needed):** `gemini-3-pro-image` — for complex visual tasks with reasoning
- **DEPRECATED:** `gemini-2.5-flash-image` — being retired Oct 2, 2026

### 11.2 SDK
- Package: `google-genai` (official Google Gen AI SDK for Python)
- Auth: API key (stored as environment variable `GEMINI_API_KEY`)

### 11.3 Usage Patterns
1. **Image-to-image editing:** Send current bundle image + edit prompt → get edited image
2. **Multi-reference editing:** Send current image + individual product photos + prompt → preserve product fidelity
3. **Conversational editing:** Multi-turn refinement (user edits, then edits again)

### 11.4 Product Fidelity Safeguards
Every Gemini prompt will include:
```
CRITICAL PRODUCT FIDELITY RULES:
- Preserve each product's original packaging, colours, labels, logos, text, and branding EXACTLY
- Do not redesign, redraw, stylise, or reinterpret any product
- Do not stretch, compress, widen, shorten, or distort packaging
- Do not invent, remove, duplicate, or alter product features
- Use the provided reference images as visual ground truth
- Product accuracy takes precedence over visual creativity
```

### 11.5 Fallback Strategy
```
Edit request arrives
    │
    ├── Can it be done programmatically (PIL)?
    │   ├── YES → Do it with PIL (instant, 100% fidelity) → return
    │   └── NO → Try Gemini API
    │       ├── Success + fidelity check passes → return
    │       ├── Success but fidelity check fails → flag for manual review
    │       └── API failure → return error, allow retry
```

---

## 12. Build Phases

### Phase 1: Complete Backend (Days 1-2)
- [x] `monday_client.py` — done
- [x] `boots_crawler.py` — done
- [x] `image_composer.py` — done
- [ ] `gemini_client.py` — Gemini API integration
- [ ] `bundle_processor.py` — quality assessment + categorization
- [ ] `app.py` — FastAPI server with all endpoints
- [ ] Test backend locally with `uvicorn`

### Phase 2: Build Frontend (Days 3-4)
- [ ] React app scaffolding (Vite)
- [ ] Dashboard component with 3 tabs
- [ ] BundleCard component (side-by-side images)
- [ ] EditPanel component (prompt input, loading, error)
- [ ] ExportButton component
- [ ] API client module
- [ ] Test frontend locally against local backend

### Phase 3: Deployment Infrastructure (Day 5)
- [ ] Create private GitHub repository
- [ ] Push code to GitHub
- [ ] Write `render.yaml` Blueprint
- [ ] Write `vercel.json` config
- [ ] Deploy backend to Render
- [ ] Deploy frontend to Vercel
- [ ] Set environment variables on both platforms
- [ ] Verify end-to-end functionality

### Phase 4: CI/CD (Day 6)
- [ ] Write `backend-ci.yml` (lint + test on PR)
- [ ] Write `backend-deploy.yml` (deploy to Render on main push)
- [ ] Write `frontend-ci.yml` (lint + build on PR)
- [ ] Write `frontend-deploy.yml` (deploy to Vercel on main push)
- [ ] Add GitHub secrets (RENDER_DEPLOY_HOOK, VERCEL_TOKEN, etc.)
- [ ] Test CI/CD pipeline with a test push

### Phase 5: Documentation & Polish (Day 7)
- [ ] Write comprehensive README.md
- [ ] Document setup, deployment, and usage instructions
- [ ] Add Dockerfile (optional, for containerized deploy)
- [ ] Final end-to-end testing
- [ ] Present complete project to user

---

## 13. What's Already Built (Can Be Reused)

These files already exist at `/workspace/boots-bundle-studio/backend/` and are complete:

| File | Status | Lines | Purpose |
|------|--------|-------|---------|
| `monday_client.py` | ✅ Complete | 310 | Monday.com API client |
| `boots_crawler.py` | ✅ Complete | 194 | Boots.com crawler |
| `image_composer.py` | ✅ Complete | 288 | PIL compositing |
| `requirements.txt` | ✅ Complete | — | Python dependencies |
| `.gitignore` | ✅ Complete | — | Python + React + env |
| `.env.example` | ✅ Complete | — | Environment variable template |

**These are solid foundations.** The remaining work is:
- `gemini_client.py` — new
- `bundle_processor.py` — new
- `app.py` — new (FastAPI server)
- All frontend files — new
- All CI/CD workflows — new
- `render.yaml`, `vercel.json` — new
- `README.md` — new

---

## 14. Cost Estimate

| Service | Plan | Monthly Cost |
|---------|------|-------------|
| Render (backend) | Starter | $7/mo |
| Vercel (frontend) | Hobby | Free |
| GitHub (private repo) | Free | Free |
| Google Gemini API | Pay-per-use | ~$0.039 per image edit (Nano Banana 2.1) |
| Monday.com API | Existing account | Free (already have access) |
| **Total** | | **~$7/mo + API usage** |

---

## 15. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Gemini API alters product fidelity | Medium | PIL compositing is primary; Gemini only for edits that can't be done programmatically. Fidelity check after every Gemini edit. |
| `gemini-2.5-flash-image` retired Oct 2026 | Low | Already planning to use `gemini-nano-banana-2.1` |
| Render free tier spins down after inactivity | Low | Use Starter plan ($7/mo) — no spin-down |
| Boots.com crawler blocked | Low | `x-agent-client` bypass already verified working |
| Monday.com API rate limits | Low | Internal tool, low volume. Cache results per session. |
| Large image uploads slow the API | Medium | Compress images before upload, set max file size, use streaming responses |
| CORS issues between Vercel and Render | Low | Configure CORS_ORIGINS env var on backend, test before launch |

---

## 16. Approval Checklist

Before we start building, please confirm:

- [ ] Technology stack is correct (FastAPI + React + PIL + Gemini)
- [ ] Gemini model choice is correct (`gemini-nano-banana-2.1`)
- [ ] Deployment targets are correct (Render backend, Vercel frontend)
- [ ] CI/CD approach is correct (GitHub Actions, separate workflows)
- [ ] Repository should be private on GitHub
- [ ] VS Code + AI coding assistant is the development environment
- [ ] The 5 build phases and timeline are acceptable
- [ ] The existing backend modules (monday_client, boots_crawler, image_composer) can be reused
- [ ] The cost estimate (~$7/mo + API usage) is acceptable
- [ ] Any additional requirements or changes?

---

**Once you approve this plan, I will begin Phase 1 (complete the backend) immediately.**
