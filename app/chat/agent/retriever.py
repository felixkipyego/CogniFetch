from typing import Optional

from langchain.tools.retriever import create_retriever_tool
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector

from app import runtime_config
from app.config import settings

_VECTOR_STORE_COLLECTION = "cognifetch_chunks"


def _build_vectorstore() -> PGVector:
    """
    Build the async PGVector store.

    Call this at most once per request. Constructing PGVector(...) registers
    a SQLAlchemy declarative class against a shared registry; building
    several instances concurrently (e.g. one per document for a fan-out
    retrieval) risks the same declarative-class-registration race fixed for
    the sync ingestion path in Phase 1. Build one store and vary only the
    retriever's search_kwargs per caller instead.
    """
    embeddings = OpenAIEmbeddings(
        model=runtime_config.get("embedding_model") or settings.embedding_model,
        api_key=runtime_config.get("api_key") or settings.api_key,
        base_url=runtime_config.get("openai_api_base") or settings.openai_api_base,
    )
    return PGVector(
        embeddings=embeddings,
        collection_name=_VECTOR_STORE_COLLECTION,
        connection=settings.database_url,
        # The `vector` extension is already created by Alembic migration 0001.
        # PGVector's own async extension-creation check runs a two-statement
        # string (advisory lock + CREATE EXTENSION) through SQLAlchemy's asyncpg
        # dialect, which can't run multiple commands in one prepared statement —
        # reproduced live. Skip the redundant, broken check entirely.
        create_extension=False,
        async_mode=True,
    )


def make_retriever_tool(document_scope: Optional[list], user_id: str):
    """
    Build a scoped retriever tool for the LangGraph agent.

    PGVector is initialised with async_mode=True so ToolNode can call
    retriever.ainvoke() inside the async graph execution without errors.

    document_scope: list of document-ID strings to restrict retrieval, or None = all docs.
    user_id:        always applied as a hard filter so users can't see each other's data.
    """
    store = _build_vectorstore()

    metadata_filter: dict = {"user_id": user_id}
    if document_scope:
        metadata_filter["document_id"] = {"$in": document_scope}

    retriever = store.as_retriever(
        search_type="mmr",
        search_kwargs={
            "filter": metadata_filter,
            "k": 10,        # chunks returned to the agent
            "fetch_k": 40,  # candidate pool MMR selects from
            "lambda_mult": 0.5,  # 0 = max diversity, 1 = max relevance
        },
    )

    return create_retriever_tool(
        retriever,
        "retrieve_documents",
        "Search the user's uploaded documents for information relevant to the question.",
    )


def make_per_document_retrievers(document_ids: list[str], user_id: str) -> dict[str, object]:
    """
    Build one retriever per document, off a single shared PGVector store, for
    the multi-document synthesis sub-agent to fan out over. See
    _build_vectorstore's docstring for why these must NOT each build their
    own store.
    """
    store = _build_vectorstore()
    retrievers = {}
    for doc_id in document_ids:
        retrievers[doc_id] = store.as_retriever(
            search_type="mmr",
            search_kwargs={
                "filter": {"user_id": user_id, "document_id": doc_id},
                "k": 10,
                "fetch_k": 40,
                "lambda_mult": 0.5,
            },
        )
    return retrievers
