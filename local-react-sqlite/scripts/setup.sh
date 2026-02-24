#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_DIR="$BACKEND_DIR/.venv"

python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r "$BACKEND_DIR/requirements.txt"

cd "$FRONTEND_DIR"
npm install

echo ""
echo "Setup complete."
echo "Run both: $ROOT_DIR/scripts/start.sh"
echo "Run backend only: $VENV_DIR/bin/uvicorn main:app --reload --host 127.0.0.1 --port 8000 --app-dir $BACKEND_DIR"
echo "Run frontend only: cd $FRONTEND_DIR && npm run dev"
