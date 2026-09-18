#!/bin/bash
# Double-click this file in Finder to start the tool.
# First run installs everything and asks for your API key; every run
# after that just starts the server and opens your browser.

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "First time setup — this only happens once..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip3 install -q -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo
  echo "============================================================"
  echo "  One more step: a text file is about to open."
  echo "  Find the line GROQ_API_KEY= and paste your key after the ="
  echo "  Get a free key at: https://console.groq.com/keys"
  echo "  Save the file, close it, then come back here and press Enter."
  echo "============================================================"
  echo
  open -e .env
  read -p "Press Enter once you've saved your key... "
fi

echo "Starting the tool..."
( sleep 2 && open "http://127.0.0.1:8020" ) &
python3 -m uvicorn app.main:app --port 8020
