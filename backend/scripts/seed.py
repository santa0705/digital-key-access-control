"""
backend/scripts/seed.py -- Convenience runner for local development seeding and resetting.

Usage:
    python backend/scripts/seed.py          # Idempotently seed local database
    python backend/scripts/seed.py --reset  # Clean and re-seed local database
"""
import sys
from pathlib import Path

# Ensure backend package is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.seed import main

if __name__ == "__main__":
    main()
