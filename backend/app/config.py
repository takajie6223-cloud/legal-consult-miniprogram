import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
DB_PATH = ROOT / "data" / "law.db"
LAWS_DB_PATH = ROOT / "data" / "laws.db"
