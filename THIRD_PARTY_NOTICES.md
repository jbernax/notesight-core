# Third-Party Open-Source Notices & Licensing Architecture

NoteSight uses an **Open-Core Architecture** that strictly separates the commercial SaaS & Mobile Platform (`backend/`, `frontend/`) from the standalone open-source Optical Music Recognition engine (`packages/notesight-omr-engine/`).

---

## 1. Architectural Separation & AGPL-3.0 Compliance

### Standalone OMR Engine (`packages/notesight-omr-engine`)
- **Package Name**: `notesight-omr-engine` (`notesight-omr` CLI)
- **License**: **GNU Affero General Public License v3.0 or later (`AGPL-3.0-or-later`)**
- **Boundary**: The NoteSight backend (`backend/app/services/omr.py`) contains zero in-process Python imports of `homr` or `notesight_omr_engine`. Instead, it invokes the standalone `notesight-omr` command-line executable across an OS subprocess boundary (`notesight-omr <image_path> --output-xml <xml_path> --output-layout <layout_json_path>`), exchanging only standard MusicXML and JSON layout files on disk.
- **Corresponding Source Availability (AGPLv3 Section 13)**: The complete Corresponding Source for `notesight-omr-engine` (including all safety and dynamic-canvas patches to `homr`) is published and maintained openly in [`packages/notesight-omr-engine/`](./packages/notesight-omr-engine/) and publicly on GitHub at [https://github.com/jbernax/notesight-omr-engine](https://github.com/jbernax/notesight-omr-engine).

---

## 2. Core Platform Backend Dependencies (`backend/requirements.txt`)

All direct dependencies of the NoteSight FastAPI Backend and Celery Workers use permissive or weak-copyleft licenses compatible with commercial SaaS and mobile distribution:

| Package | License | Purpose |
| :--- | :--- | :--- |
| `fastapi` | MIT | REST & WebSocket API framework |
| `uvicorn` | BSD-3-Clause | ASGI web server |
| `websockets` | BSD-3-Clause | Real-time collaboration WebSocket transport |
| `python-multipart` | Apache-2.0 | Multipart file upload parsing |
| `sqlalchemy` | MIT | ORM and database abstraction |
| `psycopg[binary]` | LGPL-3.0 | PostgreSQL database adapter |
| `celery` | BSD-3-Clause | Distributed task queue |
| `redis` | MIT | Broker, cache, rate limiting, and pub/sub client |
| `pypdfium2` | Apache-2.0 OR BSD-3-Clause | High-speed PDF rendering (PDFium bindings) & text/path inspection |
| `pypdf` | BSD-3-Clause | Pure-Python PDF encryption check and multi-page PDF assembly |
| `pillow` | MIT-CMU | Raster image decoding and safety validation |
| `opencv-python-headless` | Apache-2.0 | Score deskewing, adaptive illumination, and staff detection |
| `numpy` | BSD-3-Clause | Numerical array processing |
| `rapidocr` | Apache-2.0 | Optical character recognition for score titles, headers, and lyrics |
| `verovio` | LGPL-3.0 | Server-side MusicXML engraving to SVG |
| `cairosvg` | LGPL-3.0 | Server-side SVG-to-PDF vector conversion |
| `bcrypt` | Apache-2.0 | Password and backup code hashing |
| `PyJWT` | MIT | JSON Web Token signing and verification |
| `email-validator` | Unlicense | RFC-compliant email syntax validation |
| `defusedxml` | PSF-2.0 | XXE/billion-laughs safe XML parsing |
| `alembic` | MIT | Database schema migrations |
| `boto3` | Apache-2.0 | S3-compatible object storage client |
| `google-cloud-storage` | Apache-2.0 | Google Cloud Storage client |
| `stripe` | MIT | Subscription billing and webhook verification |

### LGPL-3.0 Notice (`verovio`, `cairosvg`, `psycopg`)
`verovio`, `cairosvg`, and `psycopg` are licensed under the **GNU Lesser General Public License v3.0 (LGPL-3.0)** and are dynamically imported as unmodified third-party Python packages on the server. They are never statically linked into or distributed inside the Capacitor mobile client binary.

---

## 3. Standalone OMR Engine Dependencies (`packages/notesight-omr-engine`)

| Package | License | Purpose |
| :--- | :--- | :--- |
| `notesight-omr-engine` | AGPL-3.0-or-later | Standalone CLI wrapper and safety patches around `homr` |
| `homr` | AGPL-3.0 | Transformer-based Optical Music Recognition inference |
| `opencv-python-headless` | Apache-2.0 | Canvas padding and region bounding calculations |
| `numpy` | BSD-3-Clause | Tensor/array manipulation |
| `onnxruntime` | MIT | Neural network ONNX runtime execution |

---

## 4. Frontend & Mobile Client Dependencies (`frontend/package.json`)

All frontend web and Capacitor mobile dependencies use permissive licenses:

| Package | License | Purpose |
| :--- | :--- | :--- |
| `vue` | MIT | Reactive UI framework |
| `vue-router` | MIT | Client-side routing |
| `vue-i18n` | MIT | Internationalization (EN, ES, FR, DE) |
| `opensheetmusicdisplay` | BSD-3-Clause | Interactive MusicXML browser engraving (OSMD) |
| `jszip` | MIT | Compressed `.mxl` archive extraction |
| `lucide-vue-next` | ISC | Studio and dashboard iconography |
| `@capacitor/core`, `@capacitor/app`, `@capacitor/camera`, `@capacitor/filesystem`, `@capacitor/share` | MIT | Native Android & iOS mobile bridge |
| `vite` | MIT | Frontend bundler and build toolchain |
