import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_cfg_file = ROOT / "config.json"
if not _cfg_file.exists():
    _cfg_file = ROOT / "config.example.json"
CONFIG = json.loads(_cfg_file.read_text(encoding="utf-8")) if _cfg_file.exists() else {}
DB_PATH = ROOT / "data" / "law.db"
LAWS_DB_PATH = ROOT / "data" / "laws.db"
