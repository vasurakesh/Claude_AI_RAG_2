"""
apps/document_upload/views.py
"""
import json
import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_GET

from apps.knowledge_base.models import KnowledgeBase
from core.repositories.document_repository import DocumentRepository
from core.services.document_pipeline import (
    DocumentPipelineService,
    DuplicateDocumentError,
    UnsupportedFileTypeError,
)
from core.utilities.file_utils import validate_upload
from .forms import DocumentUploadForm, DocumentSearchForm
from .models import Document

logger = logging.getLogger(__name__)

_repo     = DocumentRepository()
_pipeline = DocumentPipelineService()

PIPELINE_STEPS = [
    'Store file', 'SHA-256 hash', 'Text extraction',
    'OCR if needed', 'Normalise text', 'Save pages',
    'Chunk text', 'Generate embeddings', 'Index in vector DB',
]


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@login_required
def upload_view(request):
    form = DocumentUploadForm(request.POST or None, request.FILES or None)

    if request.method == 'POST':
        uploaded_files = request.FILES.getlist('files')
        kb_id = request.POST.get('knowledge_base')

        if not uploaded_files:
            messages.error(request, 'Please select at least one file.')
            return render(request, 'document_upload/upload.html', {
                'form': form, 'steps': PIPELINE_STEPS,
            })

        try:
            kb = KnowledgeBase.objects.get(pk=kb_id, is_active=True)
        except KnowledgeBase.DoesNotExist:
            messages.error(request, 'Invalid knowledge base selected.')
            return render(request, 'document_upload/upload.html', {
                'form': form, 'steps': PIPELINE_STEPS,
            })

        results = {'success': [], 'duplicate': [], 'failed': []}

        for f in uploaded_files:
            valid, err = validate_upload(f, f.name)
            if not valid:
                results['failed'].append(f'{f.name}: {err}')
                continue
            try:
                doc = _pipeline.ingest(
                    file_obj=f,
                    filename=f.name,
                    knowledge_base=kb,
                    uploaded_by=request.user,
                )
                results['success'].append(doc.title)
            except DuplicateDocumentError as e:
                results['duplicate'].append(
                    f'{f.name} (duplicate of "{e.existing_doc.title}")'
                )
            except UnsupportedFileTypeError as e:
                results['failed'].append(f'{f.name}: {e}')
            except Exception as e:
                logger.exception('Unexpected upload error for %s', f.name)
                results['failed'].append(f'{f.name}: {e}')

        if results['success']:
            messages.success(request,
                f"Successfully uploaded: {', '.join(results['success'])}")
        if results['duplicate']:
            messages.warning(request,
                f"Skipped duplicates: {', '.join(results['duplicate'])}")
        if results['failed']:
            messages.error(request,
                f"Failed: {', '.join(results['failed'])}")

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'results': results})

        return redirect('document_upload:list')

    return render(request, 'document_upload/upload.html', {
        'form': form, 'steps': PIPELINE_STEPS,
    })


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@login_required
def list_view(request):
    search_form = DocumentSearchForm(request.GET or None)
    q      = request.GET.get('q', '')
    status = request.GET.get('status', '')
    kb_id  = request.GET.get('kb', '')

    qs = _repo.list_all(status=status or None, search_q=q)
    if kb_id:
        qs = qs.filter(knowledge_base_id=kb_id)

    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'document_upload/list.html', {
        'page_obj':    page,
        'search_form': search_form,
        'total':       qs.count(),
    })


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

@login_required
def detail_view(request, pk: int):
    doc   = get_object_or_404(Document, pk=pk, is_deleted=False)
    pages = _repo.get_pages(doc)
    return render(request, 'document_upload/detail.html', {
        'document':    doc,
        'pages':       pages[:10],
        'total_pages': pages.count(),
    })


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@login_required
@require_POST
def delete_view(request, pk: int):
    doc = get_object_or_404(Document, pk=pk, is_deleted=False)
    _repo.soft_delete(doc, deleted_by=request.user)
    messages.success(request, f'"{doc.title}" has been deleted.')
    return redirect('document_upload:list')


# ---------------------------------------------------------------------------
# Status poll (AJAX)
# ---------------------------------------------------------------------------

@login_required
@require_GET
def status_view(request, pk: int):
    doc = get_object_or_404(Document, pk=pk, is_deleted=False)
    return JsonResponse({
        'status':       doc.status,
        'status_label': doc.get_status_display(),
        'is_indexed':   doc.is_indexed,
        'failed':       doc.failed,
        'error':        doc.processing_error,
        'page_count':   doc.page_count,
        'word_count':   doc.word_count,
    })
