"""VerifAI — backend/services/vector_store.py — ChromaDB ingestion + two-stage retrieval"""
import asyncio
import hashlib
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings as LISettings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from sentence_transformers import CrossEncoder

from config import settings as cfg

_embed_model = HuggingFaceEmbedding(model_name=cfg.embed_model, embed_batch_size=32)
LISettings.embed_model = _embed_model
LISettings.llm = None

_reranker = CrossEncoder(cfg.reranker_model, max_length=512)

_chroma = chromadb.PersistentClient(
    path=str(Path(cfg.chroma_path).resolve()),
    settings=ChromaSettings(anonymized_telemetry=False),
)
_collection = _chroma.get_or_create_collection(name="verifai_docs", metadata={"hnsw:space": "cosine"})
_vector_store = ChromaVectorStore(chroma_collection=_collection)
_storage_ctx = StorageContext.from_defaults(vector_store=_vector_store)
_index = VectorStoreIndex.from_vector_store(_vector_store, embed_model=_embed_model)
_splitter = SentenceSplitter(chunk_size=512, chunk_overlap=64, paragraph_separator="\n\n")


def _doc_id(url: str, text: str) -> str:
    return hashlib.md5((url + text[:200]).encode()).hexdigest()


async def ingest_documents(docs: list[dict]) -> dict:
    if not docs:
        return {"indexed": 0, "skipped": 0, "total_chunks": 0}
    li_docs, skipped = [], 0
    for d in docs:
        text = (d.get("text") or d.get("content") or "").strip()
        url = d.get("url", "")
        if not text or len(text) < 50:
            skipped += 1
            continue
        li_docs.append(Document(
            text=text, doc_id=_doc_id(url, text),
            metadata={"url": url, "title": d.get("title", "Untitled"),
                      "domain": url.split("/")[2] if url.startswith("http") else ""},
        ))
    if not li_docs:
        return {"indexed": 0, "skipped": skipped, "total_chunks": 0}
    nodes = _splitter.get_nodes_from_documents(li_docs)

    def _upsert():
        VectorStoreIndex(nodes, storage_context=_storage_ctx, embed_model=_embed_model, show_progress=False)
        return len(nodes)

    total = await asyncio.to_thread(_upsert)
    return {"indexed": len(li_docs), "skipped": skipped, "total_chunks": total}


async def ingest_tavily_results(results: list[dict]) -> dict:
    docs = [{"text": r.get("raw_content") or r.get("content", ""),
             "url": r.get("url", ""), "title": r.get("title", "")} for r in results]
    return await ingest_documents(docs)


async def retrieve(query: str, top_k: int = 6, candidate_k: int = 20) -> list[dict]:
    """Stage 1: vector search for candidate_k passages. Stage 2: cross-encoder re-rank to top_k."""
    def _vector_search():
        nodes = _index.as_retriever(similarity_top_k=candidate_k).retrieve(query)
        return [{"content": n.get_content(), "metadata": n.metadata, "score": n.score or 0.0} for n in nodes]

    candidates = await asyncio.to_thread(_vector_search)
    if not candidates:
        return []

    def _rerank(cands):
        scores = _reranker.predict([(query, c["content"][:512]) for c in cands])
        ranked = sorted(zip(scores, cands), key=lambda x: x[0], reverse=True)
        for score, node in ranked:
            node["rerank_score"] = float(score)
        return [node for _, node in ranked[:top_k]]

    return await asyncio.to_thread(_rerank, candidates)


async def collection_stats() -> dict:
    return {"total_chunks": await asyncio.to_thread(_collection.count), "chroma_path": cfg.chroma_path}


async def init_chroma() -> None:
    _chroma.heartbeat()
    stats = await collection_stats()
    print(f"[VerifAI] ChromaDB ready — {stats['total_chunks']} chunks indexed")
