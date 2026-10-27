# Boots Bundle Image Studio

A standalone web application for improving Boots.com virtual bundle product images. Fetches bundle data from Monday.com, assesses image quality, generates improved images using Python PIL compositing (100% product fidelity), and provides an interactive dashboard for approval, editing, and export.

## Architecture

```
┌─────────────────────┐     ┌──────────────────────────┐
│   React Frontend     │     │   FastAPI Backend         │
│   (Vercel)           │────▶│   (Render)                │
│                      │ API │                           │
│  Dashboard           │     │  ┌────────────────────┐  │
│  3 tabs              │     │  │ Monday.com Client   │  │
│  Approve/Edit/Export │     │  │ Boots.com Crawler   │  │
└─────────────────────┘     │  │ Image Composer (PIL)│  │
                            │  │ Gemini Client (AI)  │  │
                            │  │ Bundle Processor    │  │
                            │  └────────────────────┘  │
                            └──────────────────────────┘
```

## Tech Stack

- **Backend:** Python, FastAPI, Uvicorn, Pillow (PIL), google-genai SDK
- **Frontend:** React 18, Vite, JavaScript
- **AI:** Google Gemini API (Nano Banana 2.1 — `gemini-nano-banana-2.1`)
- **Hosting:** Render (backend), Vercel (frontend)
- **CI/CD:** GitHub Actions (4 workflows: backend CI/deploy, frontend CI/deploy)
- **Repository:** Private GitHub repo

## Quick Start (Local Development)

### Prerequisites

- Python 3.12+
- Node.js 20+
- Google Gemini API key
- Monday.com API token

### 1. Clone and set up environment

```bash
git clone <your-private-repo-url>
cd boots-bundle-studio
```

### 2. Backend setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root (copy from `.env.example`):

```env
GEMINI_API_KEY=your_google_gemini_api_key
MONDAY_API_TOKEN=your_monday_com_api_token
MONDAY_BOARD_ID=5100428483
BOOTS_X_AGENT_CLIENT=W-7njoVr89mFAk
CORS_ORIGINS=http://localhost:5173
UPLOADS_DIR=uploads
```

Start the backend:

```bash
cd backend
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Backend will be running at `http://localhost:8000`.

Health checks:
- `http://localhost:8000/healthz` — liveness
- `http://localhost:8000/readyz` — readiness (verifies API keys)

### 3. Frontend setup

```bash
cd frontend
npm install
```

Create a `.env` file (copy from `.env.example`):

```env
VITE_API_URL=http://localhost:8000
```

Start the frontend:

```bash
npm run dev
```

Frontend will be running at `http://localhost:5173`.

### 4. Open in VS Code

Open the `boots-bundle-studio` folder in VS Code:

```bash
code .
```

VS Code will detect both the Python backend and React frontend. Recommended extensions:
- Python (Microsoft)
- Pylance
- ESLint
- GitHub Pull Requests

### 5. Using AI coding assistant (optional)

If you have the AI coding assistant VS Code extension installed, you can use it to:
- Write new modules: "Write a test for image_composer.py"
- Debug issues: "The /api/edit endpoint returns 500, find the bug"
- Refactor code: "Add error handling to all API endpoints"
- Generate docs: "Write docstrings for all functions in gemini_client.py"

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | Liveness check |
| GET | `/readyz` | Readiness check (verifies API keys) |
| GET | `/api/bundles` | Fetch all bundles, assess quality, categorize |
| GET | `/api/bundle/{code}` | Get details for a specific bundle |
| POST | `/api/generate` | Compose a bundle image from product photos (PIL) |
| POST | `/api/edit` | Edit a bundle image (PIL first, Gemini fallback) |
| POST | `/api/approve` | Mark a bundle image as approved |
| POST | `/api/reject` | Send a bundle back to manual review |
| GET | `/api/approved` | List all approved bundles |
| GET | `/api/export` | Export all approved images as ZIP |
| POST | `/api/upload` | Upload a supplier-provided image |
| GET | `/api/images/{filename}` | Serve an image from uploads |

## Deployment

### Backend → Render

1. Create a Render account at [render.com](https://render.com)
2. Create a new Web Service → connect your GitHub repo
3. Configure:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path:** `/healthz`
   - **Root Directory:** `backend/`
4. Add environment variables (in Render dashboard):
   - `GEMINI_API_KEY`
   - `MONDAY_API_TOKEN`
   - `MONDAY_BOARD_ID`
   - `BOOTS_X_AGENT_CLIENT`
   - `CORS_ORIGINS` (set to your Vercel URL after frontend deploy)
5. Deploy

Or use the `render.yaml` Blueprint for Infrastructure as Code.

### Frontend → Vercel

1. Create a Vercel account at [vercel.com](https://vercel.com)
2. Install Vercel CLI: `npm install --global vercel@latest`
3. Link the project:
   ```bash
   cd frontend
   vercel link
   ```
4. Save the project ID and org ID from `.vercel/project.json`
5. Set environment variable `VITE_API_URL` to your Render backend URL
6. Deploy: `vercel --prod`

### CI/CD with GitHub Actions

The repository includes 4 GitHub Actions workflows:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `backend-ci.yml` | PR to main | Lint + syntax check backend |
| `backend-deploy.yml` | Push to main | Deploy backend to Render |
| `frontend-ci.yml` | PR to main | Build check frontend |
| `frontend-deploy.yml` | Push to main | Deploy frontend to Vercel |

**Required GitHub Secrets:**

| Secret | Description |
|--------|-------------|
| `RENDER_DEPLOY_HOOK` | Render deploy hook URL |
| `VERCEL_TOKEN` | Vercel API token |
| `VERCEL_ORG_ID` | Vercel organization ID |
| `VERCEL_PROJECT_ID` | Vercel project ID |

## Project Structure

```
boots-bundle-studio/
├── .github/workflows/          # CI/CD pipelines
├── backend/
│   ├── app.py                  # FastAPI server
│   ├── monday_client.py        # Monday.com API client
│   ├── boots_crawler.py        # Boots.com crawler
│   ├── image_composer.py       # PIL compositing (100% fidelity)
│   ├── gemini_client.py        # Google Gemini API
│   ├── bundle_processor.py     # Quality assessment + categorization
│   ├── requirements.txt        # Python dependencies
│   └── Dockerfile              # Container deployment
├── frontend/
│   ├── src/
│   │   ├── App.jsx             # Main app component
│   │   ├── components/         # React components
│   │   ├── api/                # API client
│   │   └── styles/             # CSS
│   ├── package.json
│   ├── vite.config.js
│   └── vercel.json
├── .env.example
├── .gitignore
├── render.yaml                 # Render Blueprint
└── README.md
```

## How It Works

1. **Fetch:** Backend fetches Virtual Bundle data from Monday.com (Core Line List + 2am Report), cross-references to find confirmed live bundles
2. **Crawl:** Backend crawls Boots.com for each bundle's current image and individual product photos
3. **Assess:** Bundle Processor evaluates image quality (background, spacing, aspect ratio, badges)
4. **Categorize:** Bundles sorted into Ready for Approval, Supplier Image Required, or Manual Review Required
5. **Generate:** PIL composites individual product photos onto a 2000×2000 white canvas with visible gaps, shadows, and roundel (for 6+ identical items)
6. **Review:** User reviews side-by-side (original vs generated) in the dashboard
7. **Edit:** User can edit with natural language (PIL for spacing/size, Gemini AI for complex edits)
8. **Approve:** User approves images, which are stored for export
9. **Export:** All approved images exported as ZIP with correct 8-digit Boots bundle codes as filenames

## Image Rules

- 2000×2000 pixel canvas, pure white background
- Only outer product packaging shown (never inner contents)
- Visible gaps between products (NO overlap)
- Subtle realistic contact shadows
- All branding, text, and labels fully visible and legible
- No number badges (x3, x5) — bad for SEO. Exception: roundel for 6+ identical items
- Products on common horizontal baseline
- Product fidelity is paramount — never alter colours, artwork, text, proportions

## License

Proprietary — Boots UK