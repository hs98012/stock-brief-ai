"""Read-only cProfile of one hybrid_search call on a test-v2 case (latency only; no tuning)."""
import cProfile, json, pstats, sys
from datetime import date
from pathlib import Path

ROOT = Path(sys.argv[1]); sys.path.insert(0, str(ROOT / "backend"))
from sqlalchemy import text  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.embeddings import OllamaEmbeddingProvider  # noqa: E402
from app.models import Document  # noqa: E402
from app.search import SearchFilters, hybrid_search  # noqa: E402

case = next(c for c in json.loads((ROOT / "evals/test-v2-cases.json").read_text()) if c["id"] == sys.argv[2])
provider = OllamaEmbeddingProvider()
with SessionLocal() as db:
    for sql in ("SET TRANSACTION READ ONLY", "SET LOCAL enable_indexscan = off", "SET LOCAL enable_bitmapscan = off"):
        db.execute(text(sql))
    doc = db.query(Document).filter(Document.company_name == case["company_name"],
                                    Document.published_at == date.fromisoformat(case["published_at"])).one()
    profiler = cProfile.Profile(); profiler.enable()
    hybrid_search(db, case["question"], 5, SearchFilters(document_id=doc.id), provider)
    profiler.disable(); db.rollback()
pstats.Stats(profiler).sort_stats("cumulative").print_stats(30)
