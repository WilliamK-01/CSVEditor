# Local React + SQLite App

This is a local-first alternative UI for CSVEditor using:

- **Frontend:** React + Vite
- **Backend:** FastAPI
- **Storage:** SQLite (`backend/transactions.db`)

## Quick setup

### Linux / macOS

```bash
cd local-react-sqlite
./scripts/setup.sh
```

### Windows (PowerShell)

```powershell
cd local-react-sqlite
./scripts/setup.ps1
```

## Run

### Backend

```bash
cd local-react-sqlite
./backend/.venv/bin/uvicorn main:app --reload --host 127.0.0.1 --port 8000 --app-dir backend
```

Windows:

```powershell
cd local-react-sqlite
./backend/.venv/Scripts/uvicorn.exe main:app --reload --host 127.0.0.1 --port 8000 --app-dir backend
```

### Frontend

```bash
cd local-react-sqlite/frontend
npm run dev
```

Then open `http://127.0.0.1:5173`.

## What this includes

- Create transaction
- List all transactions
- Toggle verified status
- Delete transaction
- Data persisted locally in SQLite
