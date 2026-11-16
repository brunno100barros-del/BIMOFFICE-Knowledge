"""Referência do backend atual (Python): trechos, vetores E5 e resultados da pesquisa híbrida no exemplo."""
import json, os, sys, tempfile
from pathlib import Path
out = Path(sys.argv[1])
tmp = tempfile.mkdtemp()
os.environ["BIMOFFICE_DATA_DIR"] = tmp
sys.path.insert(0, os.getcwd())
from backend import config
from backend.database.db import init_db
init_db()
from backend.services import library_service as lib
from backend.semantic_search import hybrid, vector_store
from backend.semantic_search.providers import get_provider
for f in sorted(Path("exemplos/memoriais_referencia").glob("*.docx")):
    lib.import_document(f.name, f.read_bytes(), {})
vector_store.index_pending()
chunks = []
for d in lib.list_documents():
    for c in lib.list_chunks(d["id"]):
        chunks.append({"id": c["id"], "doc": d["original_filename"], "section": c.get("section_path"), "text": c["text"]})
queries = ["paredes dos banheiros com placas cerâmicas", "proteção contra descargas atmosféricas",
           "concreto das sapatas", "tubulação de água fria", "impermeabilização da laje",
           "pintura das paredes internas", "esquadrias de alumínio", "quadro de distribuição elétrica",
           "forro de gesso", "drenagem de águas pluviais"]
p = get_provider()
res = {}
for q in queries:
    r = hybrid.search(q, limit=5)
    items = r["results"] if isinstance(r, dict) else r
    res[q] = [{"id": it.get("chunk_id") or it.get("id"), "section": it.get("section_path")} for it in items]
qv = p.embed_query(queries[0]); pv = p.embed_passages([chunks[0]["text"]])
json.dump({"model": p.name, "chunks": chunks, "queries": queries, "results": res,
           "sample_query_vec": qv.reshape(-1).tolist(), "sample_passage_vec": pv.reshape(-1).tolist()},
          open(out, "w", encoding="utf-8"), ensure_ascii=False)
print("ok", len(chunks), "trechos", p.name)
