# Activity Telemetry Client

macOS Python client that collects mouse/keyboard activity and flushes it to MongoDB Atlas every 60 seconds.

## Setup

```bash
cd activity-telemetry-client
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Create `.env` (see `.env.example`):

```text
MONGO_URI=mongodb+srv://...
ACTIVITY_DB_NAME=activity-telemetry
```

## Permissions

- **Input Monitoring**: required for the mouse listener.
- **Accessibility**: required for the keyboard listener.

Grant them in System Settings → Privacy & Security. If either is missing, the corresponding collector will be disabled.

## Run

```bash
python main.py
```

## Test

```bash
python -m pytest tests/ -v
```

## Smoke test

1. Run `python main.py`.
2. Click and type for at least 60 seconds.
3. Check MongoDB Atlas for documents in the configured database and `telemetry` collection.
