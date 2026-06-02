from __future__ import annotations

import logging
from typing import Sequence

from sentence_transformers import SentenceTransformer

from ..database import get_chroma_collection
from ..models import KnowledgeItem as KnowledgeItemModel

logger = logging.getLogger(__name__)

# Lazily initialised model — loaded once and cached globally.
_embed_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


def _build_embedding_text(item: KnowledgeItemModel) -> str:
    """Build the text string that is encoded for the ChromaDB embedding."""
    parts = [item.title]
    if item.summary:
        parts.append(item.summary)
    parts.append(item.content[:2000])
    return "\n".join(parts)


def embed_knowledge_item(item: KnowledgeItemModel) -> list[float]:
    return _get_model().encode(_build_embedding_text(item)).tolist()


def embed_and_upsert(db_items: Sequence[KnowledgeItemModel]) -> int:
    """Embed a batch of KnowledgeItems and upsert into ChromaDB. Returns count upserted."""
    if not db_items:
        return 0

    collection = get_chroma_collection()
    # Filter to items that don't already have an embedding_id
    pending = [item for item in db_items if not item.embedding_id]
    if not pending:
        return 0

    texts = [_build_embedding_text(item) for item in pending]
    embeddings = _get_model().encode(texts, show_progress_bar=False).tolist()

    ids = [item.id for item in pending]
    metadatas = [
        {
            "source_type": item.source_type,
            "title": item.title[:256],
            "source_document": item.source_document[:256],
        }
        for item in pending
    ]

    try:
        collection.upsert(ids=ids, embeddings=list(embeddings), metadatas=metadatas)
        for item in pending:
            item.embedding_id = f"emb-{item.id}"
        return len(pending)
    except Exception:
        logger.exception("ChromaDB upsert failed for %d items", len(pending))
        return 0


def embed_all_pending(db_session) -> int:
    """Embed all active KnowledgeItems that don't yet have an embedding_id."""
    from sqlalchemy.orm import Session

    session: Session = db_session
    items = (
        session.query(KnowledgeItemModel)
        .filter(KnowledgeItemModel.is_active == True)
        .all()
    )
    n = embed_and_upsert(items)
    if n:
        session.commit()
    return n


def embed_query(text: str) -> list[float]:
    return _get_model().encode(text).tolist()
