# NoteSight Core

NoteSight Core is an open-source sheet music sight-reading, digitization, and Optical Music Recognition (OMR) system. It converts sheet music (PDFs or images) into standard MusicXML via a deep-learning neural pipeline and provides responsive vector sheet music rendering and playback directly in the browser.

---

## Features

- **Multi-Page Digitization**: Upload PDF scores or sheet music images (`.pdf`, `.png`, `.jpg`).
- **Neural OMR Engine**: ONNX-accelerated neural recognition for staves, clefs, accidentals, dynamics, and notes.
- **Continuous Score Stitching**: Automatically merges multi-page transcriptions into sequential measures.
- **Interactive Browser Playback**: Responsive vector rendering via OpenSheetMusicDisplay (OSMD) with synchronized cursor tracking and Web Audio synthesis.
- **MusicXML Export**: Download digitized notation files compatible with MuseScore, Sibelius, and Finale.
- **Local & Private**: Runs on your own machine or private server with zero third-party telemetry.

---

## Quick Start (Docker Compose)

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (version 24.0 or newer)
- [Docker Compose](https://docs.docker.com/compose/) (version 2.20 or newer)

### Running the Application

1. Clone the repository:
   ```bash
   git clone https://github.com/jbernax/notesight-core.git
   cd notesight-core
   ```

2. Copy the environment configuration template:
   ```bash
   cp .env.example .env
   ```

3. Build and launch all services:
   ```bash
   docker compose up -d --build
   ```

4. Open your browser:
   - **Web Interface**: [http://localhost:8080](http://localhost:8080)
   - **API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)

To stop the services:
```bash
docker compose down
```

---

## Architecture Overview

```
                  ┌──────────────────────┐
                  │    Vue 3 Frontend    │
                  │   (Nginx on :8080)   │
                  └──────────┬───────────┘
                             │ HTTP / REST
                             ▼
                  ┌──────────────────────┐
                  │  FastAPI API Server  │
                  │       (:8000)        │
                  └──────────┬───────────┘
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
   ┌─────────────────┐               ┌─────────────────┐
   │  PostgreSQL DB  │               │   Redis Queue   │
   │     (:5432)     │               └────────┬────────┘
   └─────────────────┘                        │ Celery
                                              ▼
                                     ┌─────────────────┐
                                     │  Celery Worker  │
                                     │ (PyMuPDF + homr)│
                                     └─────────────────┘
```

---

## Local Development (Without Docker)

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e ../packages/notesight-omr-engine

# Start API server
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# Accessible at http://localhost:5173
```

---

## License & Third-Party Notices

NoteSight Core is free software licensed under the **GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)**. See the [LICENSE](LICENSE) file for complete license terms.

Third-party component licenses are documented in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
