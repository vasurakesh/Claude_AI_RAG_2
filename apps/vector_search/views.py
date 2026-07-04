"""
apps/vector_search/views.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Search view — takes a query, runs retrieval, renders results with citations.
"""
import logging
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from core.agents.retriever import RetrievalService
from core.ai.ollama_client import OllamaError

logger = logging.getLogger(__name__)
_retriever = RetrievalService()


@login_required
@require_GET
def search_view(request):
    query = request.GET.get("q", "").strip()
    kb_id = request.GET.get("kb") or None
    results = None
    error   = None

    if query:
        try:
            results = _retriever.retrieve(
                query=query,
                knowledge_base_id=int(kb_id) if kb_id else None,
                user=request.user,
            )
        except OllamaError as e:
            error = f"Ollama is not running or the embedding model is not loaded: {e}"
        except Exception as e:
            logger.exception("Search error")
            error = str(e)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        if error:
            return JsonResponse({"error": error}, status=503)
        if results:
            return JsonResponse({
                "query": query,
                "chunks": [
                    {
                        "rank":         rc.rank,
                        "score":        rc.final_score,
                        "document":     rc.document.title,
                        "page":         rc.chunk.page_number,
                        "text_preview": rc.chunk.text[:300],
                    }
                    for rc in results.chunks
                ],
                "embedding_ms": results.embedding_time_ms,
                "search_ms":    results.search_time_ms,
            })

    from apps.knowledge_base.models import KnowledgeBase
    from apps.document_upload.models import Document
    from apps.embedding_service.models import DocumentChunk
    return render(request, "vector_search/search.html", {
        "query":            query,
        "results":          results,
        "error":            error,
        "knowledge_bases":  KnowledgeBase.objects.filter(is_active=True, is_deleted=False),
        "selected_kb":      kb_id,
        "document_count":   Document.objects.filter(status="indexed", is_deleted=False).count(),
        "chunk_count":      DocumentChunk.objects.filter(is_embedded=True).count(),
    })
