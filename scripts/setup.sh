#!/bin/bash
# PropOS local setup script
# Run once: chmod +x scripts/setup.sh && ./scripts/setup.sh

set -e
cd "$(dirname "$0")/.."

echo "=== PropOS Setup ==="

# Python virtual environment
if [ ! -d ".venv" ]; then
  # Python 3.14 is not yet supported by pydantic-core — use 3.13
  if command -v python3.13 &>/dev/null; then
    python3.13 -m venv .venv
  elif command -v python3.12 &>/dev/null; then
    python3.12 -m venv .venv
  else
    echo "ERROR: Python 3.12 or 3.13 required. 3.14 is not yet supported by pydantic."
    exit 1
  fi
  echo "✅ Virtual environment created with $(.venv/bin/python --version)"
fi

source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "✅ Dependencies installed"

# Copy .env if not exists
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "✅ .env created — fill in your API keys"
  echo ""
  echo "Keys needed:"
  echo "  ANTHROPIC_API_KEY  → https://console.anthropic.com"
  echo "  GEMINI_API_KEY     → https://aistudio.google.com"
  echo "  GROQ_API_KEY       → https://console.groq.com"
  echo "  URA_ACCESS_KEY     → https://www.ura.gov.sg/maps/api/reg.html"
  echo "  TELEGRAM_BOT_TOKEN → @BotFather on Telegram"
fi

# Create cache dirs
mkdir -p cache/ura cache/hdb cache/news cache/llm_responses logs
echo "✅ Cache directories created"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys"
echo "  2. source .venv/bin/activate"
echo "  3. python scripts/sync_ura.py        # Fetch URA data"
echo "  4. python scripts/sync_hdb.py        # Fetch HDB data"
echo "  5. python scripts/sync_news.py       # Fetch news"
echo "  6. streamlit run dashboard/app.py    # Launch dashboard"
echo "  7. python -m uvicorn api.main:app --reload  # Launch API"
