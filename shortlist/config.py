import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("SHORTLIST_DATA", str(ROOT / "data")))
MODEL_MANIFEST = Path(os.getenv("SHORTLIST_MODEL_MANIFEST", str(ROOT / "models/model.json")))
EMBEDDING_PATH = Path(os.getenv("SHORTLIST_EMBEDDINGS", str(ROOT / "models/embedding")))
MODEL_PORT = int(os.getenv("SHORTLIST_MODEL_PORT", "8778"))
PORT = int(os.getenv("SHORTLIST_PORT", "8777"))
FRESH_HOURS = 24

def initialize():
    DATA.mkdir(parents=True, exist_ok=True)
    (ROOT / "reports").mkdir(exist_ok=True)

