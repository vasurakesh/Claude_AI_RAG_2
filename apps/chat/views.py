"""
apps/chat/views.py
~~~~~~~~~~~~~~~~~~~
Chat interface views — conversation list, chat page, message send (AJAX),
conversation management, and a streaming-compatible send endpoint.
"""
import json
import logging
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.knowledge_base.models import KnowledgeBase
from core.agents.rag_agent import rag_agent
from core.ai.ollama_client import OllamaError
from .models import Conversation, Message, MessageChunkCitation

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Conversation list / index
# ──────────────────────────────────────────────────────────────────────────────

@login_required
def index_view(request):
    """Landing page — list of user's conversations + option to start new."""
    conversations = Conversation.objects.filter(
        user=request.user, is_deleted=False
    ).order_by("-last_message_at", "-created_at")

    paginator = Paginator(conversations, 20)
    page = paginator.get_page(request.GET.get("page"))

    knowledge_bases = KnowledgeBase.objects.filter(
        is_active=True, is_deleted=False
    ).order_by("name")

    return render(request, "chat/index.html", {
        "page_obj": page,
        "knowledge_bases": knowledge_bases,
    })


# ──────────────────────────────────────────────────────────────────────────────
# Start a new conversation
# ──────────────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def new_conversation_view(request):
    kb_id = request.POST.get("knowledge_base_id") or None
    title = request.POST.get("title", "").strip() or ""
    conv  = Conversation.objects.create(
        user=request.user,
        knowledge_base_id=kb_id or None,
        title=title,
    )
    return redirect("chat:conversation", pk=conv.pk)


# ──────────────────────────────────────────────────────────────────────────────
# Conversation detail (chat page)
# ──────────────────────────────────────────────────────────────────────────────

@login_required
def conversation_view(request, pk: int):
    conv = get_object_or_404(
        Conversation, pk=pk, user=request.user, is_deleted=False
    )
    messages_qs = Message.objects.filter(
        conversation=conv, is_deleted=False
    ).select_related("model_used").order_by("sequence")

    # Pre-fetch citations for assistant messages
    assistant_ids = [
        m.pk for m in messages_qs if m.role == Message.Role.ASSISTANT
    ]
    citations_map: dict[int, list] = {}
    if assistant_ids:
        for cit in MessageChunkCitation.objects.filter(
            message_id__in=assistant_ids
        ).select_related("chunk__document").order_by("rank"):
            citations_map.setdefault(cit.message_id, []).append(cit)

    message_data = []
    for msg in messages_qs:
        message_data.append({
            "msg":       msg,
            "citations": citations_map.get(msg.pk, []),
        })

    knowledge_bases = KnowledgeBase.objects.filter(
        is_active=True, is_deleted=False
    ).order_by("name")

    # Sidebar: other conversations for quick switching
    sidebar_convs = Conversation.objects.filter(
        user=request.user, is_deleted=False
    ).exclude(pk=pk).order_by("-last_message_at")[:15]

    suggestion_questions = [
        "What are the main topics covered?",
        "Summarise the key findings",
        "What recommendations are made?",
        "Who are the key people mentioned?",
    ]
    return render(request, "chat/conversation.html", {
        "conversation":    conv,
        "message_data":    message_data,
        "knowledge_bases": knowledge_bases,
        "sidebar_convs":   sidebar_convs,
        "suggestion_questions": suggestion_questions,
    })


# ──────────────────────────────────────────────────────────────────────────────
# Send message (AJAX POST → JSON response)
# ──────────────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def send_message_view(request, pk: int):
    """
    AJAX endpoint: receives a question, runs the RAG pipeline, returns JSON.
    The chat template calls this via fetch() and renders the reply.
    """
    conv = get_object_or_404(
        Conversation, pk=pk, user=request.user, is_deleted=False
    )

    try:
        payload  = json.loads(request.body)
        question = payload.get("question", "").strip()
    except (json.JSONDecodeError, AttributeError):
        question = request.POST.get("question", "").strip()

    if not question:
        return JsonResponse({"error": "Question cannot be empty."}, status=400)

    if len(question) > 4000:
        return JsonResponse({"error": "Question too long (max 4000 chars)."}, status=400)

    try:
        answer = rag_agent.ask(
            question=question,
            conversation=conv,
            user=request.user,
            knowledge_base_id=(
                conv.knowledge_base_id if conv.knowledge_base_id else None
            ),
        )
    except OllamaError as e:
        return JsonResponse({
            "error": "Ollama is offline. Please start it with: ollama serve",
            "detail": str(e),
        }, status=503)
    except Exception as e:
        logger.exception("Unexpected error in RAG pipeline for conv #%d", pk)
        return JsonResponse({"error": str(e)}, status=500)

    # Serialise sources for the UI citations panel
    sources = [
        {
            "rank":             s.rank,
            "document_title":   s.document_title,
            "filename":         s.original_filename,
            "page_number":      s.page_number,
            "paragraph_number": s.paragraph_number,
            "score":            s.display_score,
            "preview":          s.chunk_text_preview[:300],
        }
        for s in answer.sources
    ]

    return JsonResponse({
        "answer":           answer.text,
        "sources":          sources,
        "model_used":       answer.model_used,
        "generation_ms":    round(answer.generation_time_ms, 0),
        "prompt_tokens":    answer.prompt_tokens,
        "completion_tokens": answer.completion_tokens,
        "is_fallback":      answer.is_fallback,
        "chunks_used":      answer.chunks_used,
        "context_tokens":   answer.context_token_count,
    })


# ──────────────────────────────────────────────────────────────────────────────
# Rename / delete conversation
# ──────────────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def rename_conversation_view(request, pk: int):
    conv  = get_object_or_404(Conversation, pk=pk, user=request.user, is_deleted=False)
    title = request.POST.get("title", "").strip()
    if title:
        conv.title = title[:500]
        conv.save(update_fields=["title"])
    return JsonResponse({"status": "ok", "title": conv.title})


@login_required
@require_POST
def delete_conversation_view(request, pk: int):
    conv = get_object_or_404(Conversation, pk=pk, user=request.user, is_deleted=False)
    conv.delete()
    return redirect("chat:index")


# ──────────────────────────────────────────────────────────────────────────────
# Message history API (for conversation re-load)
# ──────────────────────────────────────────────────────────────────────────────

@login_required
@require_GET
def message_history_view(request, pk: int):
    conv = get_object_or_404(Conversation, pk=pk, user=request.user, is_deleted=False)
    msgs = Message.objects.filter(
        conversation=conv, is_deleted=False
    ).order_by("sequence").values(
        "pk", "role", "content", "sequence",
        "generation_time_ms", "prompt_tokens", "completion_tokens",
        "is_fallback_response",
    )
    return JsonResponse({"messages": list(msgs)})
