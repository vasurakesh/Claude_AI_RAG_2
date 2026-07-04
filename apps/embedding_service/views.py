"""
apps/embedding_service/views.py
— Chunk inspector, re-index trigger, and embedding stats API.
"""
import logging
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.document_upload.models import Document
from apps.embedding_service.models import DocumentChunk, EmbeddingRecord
from core.embeddings.embedding_service import EmbeddingService
from core.embeddings.vector_store import VectorStoreFactory

logger = logging.getLogger(__name__)
is_staff = user_passes_test(lambda u: u.is_staff)


@login_required
def chunk_list_view(request, doc_pk: int):
    """Show all chunks for a document (paginated)."""
    doc = get_object_or_404(Document, pk=doc_pk, is_deleted=False)
    qs  = DocumentChunk.objects.filter(document=doc).order_by("chunk_index")
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "embedding_service/chunk_list.html", {
        "document": doc,
        "page_obj": page,
    })


@login_required
@is_staff
@require_POST
def reindex_view(request, doc_pk: int):
    """Trigger re-indexing for a document (staff only)."""
    doc = get_object_or_404(Document, pk=doc_pk, is_deleted=False)
    service = EmbeddingService()
    service.delete_document_vectors(doc)
    doc.status = Document.Status.CHUNKING
    doc.save(update_fields=["status"])
    summary = service.index_document(doc, force=True)
    return JsonResponse({"status": "ok", "summary": summary})


@login_required
def vector_store_stats_view(request):
    """JSON stats for the vector store (used by dashboard health widget)."""
    try:
        store = VectorStoreFactory.get()
        total = store.count()
        healthy = store.health_check()
    except Exception as e:
        return JsonResponse({"error": str(e), "healthy": False})
    return JsonResponse({
        "healthy": healthy,
        "total_vectors": total,
        "backend": getattr(__import__("django.conf", fromlist=["settings"]).settings,
                          "VECTOR_DB_BACKEND", "chromadb"),
    })
