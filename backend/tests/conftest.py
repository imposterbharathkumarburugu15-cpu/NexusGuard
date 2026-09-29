import os
import sys
from pathlib import Path

backend_dir = str(Path(__file__).resolve().parents[1])
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

os.environ.setdefault("CHAT_RATE_LIMIT_PER_MINUTE", "10000")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "50000")
os.environ.setdefault("LOGIN_RATE_LIMIT_PER_MINUTE", "10000")
os.environ.setdefault("GUEST_RATE_LIMIT_PER_MINUTE", "10000")

