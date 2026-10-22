# FreqEnforcer v2.0.0

<img width="2882" height="1863" alt="image" src="https://github.com/user-attachments/assets/27cff08b-bf79-4f26-a7e6-c827944c6cbb" />

## Development

### Prerequisites
- Node.js 18+
- Python 3.10+

### Setup

```bash
npm install
pip install -r requirements.txt
```

### Run

```bash
npm run dev
```

This starts the Vite dev server (port 5174) and Electron. Electron launches its
own FastAPI backend with `--port 0` (an OS-assigned free port, announced on
stdout as `FREQENFORCER_PORT=<n>`), so several instances never collide.

### Individual services

```bash
npm run dev:server    # FastAPI only, on port 8765 (pass --port N / --port 0 to change)
npm run dev:vite      # Vite only
npm run dev:electron  # Electron only (also starts its own backend)
```

### Tests

```bash
pytest tests/                       # golden DSP regression + multisample tests (~4-7 min)
python tests/smoke_backend.py       # HTTP smoke test of the built backend exe
```

Golden references and fixtures are stored with Git LFS (`git lfs install`
once, then `git lfs pull`).
