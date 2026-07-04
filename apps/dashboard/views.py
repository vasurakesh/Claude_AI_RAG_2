import logging
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from apps.document_upload.models import Document
from apps.embedding_service.models import DocumentChunk
from apps.chat.models import Conversation

logger = logging.getLogger(__name__)


@login_required
def index(request):
    stats = {
        'total_documents':    Document.objects.count(),
        'indexed_documents':  Document.objects.filter(status='indexed').count(),
        'pending_documents':  Document.objects.filter(status__in=['pending', 'processing']).count(),
        'total_chunks':       DocumentChunk.objects.count(),
        'total_conversations': Conversation.objects.filter(user=request.user).count(),
    }
    recent_documents = Document.objects.select_related('knowledge_base').order_by('-created_at')[:8]
    recent_conversations = Conversation.objects.filter(
        user=request.user
    ).order_by('-last_message_at')[:5]
    health = {
        'vector_store': True,   # Real health check wired in Phase 6
    }
    return render(request, 'dashboard/index.html', {
        'stats': stats,
        'recent_documents': recent_documents,
        'recent_conversations': recent_conversations,
        'health': health,
    })
