from typing import Optional

from langchain.tools.retriever import create_retriever_tool
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector

from app import runtime_config
from app.config import settings


def make_retriever_tool(document_scope: Optional[list], user_id: str):
    """
    Build a scoped retriever tool for the LangGraph agent.

    PGVector is initialised with async_mode=True so ToolNode can call
    retriever.ainvoke() inside the async graph execution without errors.

    document_scope: list of document-ID strings to restrict retrieval, or None = all docs.
    user_id:        always applied as a hard filter so users can't see each other's data.
    """
    embeddings = OpenAIEmbeddings(
        model=runtime_config.get("embedding_model") or settings.embedding_model,
        api_key=runtime_config.get("api_key") or settings.api_key,
        base_url=runtime_config.get("openai_api_base") or settings.openai_api_base,
    )
    store = PGVector(
        embeddings=embeddings,
        collection_name="cognifetch_chunks",
        connection=settings.database_url,
        async_mode=True,
    )

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
