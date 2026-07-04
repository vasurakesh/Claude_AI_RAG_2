"""
core/repositories/document_repository.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Repository pattern: all Document/DocumentPage DB access goes through here
so views and services never build ORM queries directly.
"""
import logging
from typing import Optional
from apps.document_upload.models import Document, DocumentPage
from apps.knowledge_base.models import KnowledgeBase

logger = logging.getLogger(__name__)


class DocumentRepository:

    # -- Reads ----------------------------------------------------------------

    def get_by_id(self, pk: int) -> Optional[Document]:
        return Document.objects.select_related(
            'knowledge_base', 'created_by', 'parent_document'
        ).filter(pk=pk, is_deleted=False).first()

    def get_by_hash(self, sha256: str) -> Optional[Document]:
        return Document.objects.filter(
            sha256_hash=sha256, is_deleted=False
        ).first()

    def list_for_kb(
        self,
        kb: KnowledgeBase,
        status: Optional[str] = None,
        search_q: str = '',
        order_by: str = '-created_at',
    ):
        qs = Document.objects.filter(
            knowledge_base=kb, is_deleted=False
        ).select_related('knowledge_base', 'created_by')
        if status:
            qs = qs.filter(status=status)
        if search_q:
            qs = qs.filter(title__icontains=search_q)
        return qs.order_by(order_by)

    def list_all(
        self,
        status: Optional[str] = None,
        search_q: str = '',
        order_by: str = '-created_at',
    ):
        qs = Document.objects.filter(is_deleted=False).select_related(
            'knowledge_base', 'created_by'
        )
        if status:
            qs = qs.filter(status=status)
        if search_q:
            qs = qs.filter(title__icontains=search_q)
        return qs.order_by(order_by)

    def get_pages(self, document: Document):
        return document.pages.order_by('page_number')

    def pending_for_processing(self):
        return Document.objects.filter(
            status__in=[Document.Status.PENDING, Document.Status.CHUNKING],
            is_deleted=False,
        ).order_by('created_at')

    # -- Writes ---------------------------------------------------------------

    def soft_delete(self, doc: Document, deleted_by=None) -> None:
        doc.is_deleted = True
        doc.modified_by = deleted_by
        doc.save(update_fields=['is_deleted', 'deleted_at', 'modified_by'])

    def update_status(self, doc: Document, status: str, error: str = '') -> None:
        doc.status = status
        if error:
            doc.processing_error = error
        doc.save(update_fields=['status', 'processing_error'])
