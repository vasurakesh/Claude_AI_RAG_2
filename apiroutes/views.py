"""
apiroutes/views.py
~~~~~~~~~~~~~~~~~~~
DRF ViewSets and APIViews for every REST endpoint.

Spec: Upload / Search / Embedding / Chat / Documents / OCR / Settings /
      Users / Conversation / Health Check
"""
import logging
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status, viewsets, permissions
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chat.models import Conversation, Message
from apps.document_upload.models import Document
from apps.embedding_service.models import DocumentChunk
from apps.knowledge_base.models import KnowledgeBase
from apps.ocr_engine.models import OCRJob
from apps.settings_app.models import PlatformSetting
from apps.ai_agent.models import AIModel, PromptTemplate, AgentConfig
from core.agents.rag_agent import rag_agent
from core.agents.retriever import RetrievalService
from core.ai.ollama_client import OllamaClient, OllamaError
from core.embeddings.vector_store import VectorStoreFactory
from core.services.document_pipeline import (
    DocumentPipelineService, DuplicateDocumentError, UnsupportedFileTypeError,
)
from core.utilities.file_utils import validate_upload
from .serializers import (
    AgentConfigSerializer, AIModelSerializer, ChatRequestSerializer,
    ConversationDetailSerializer, ConversationSerializer,
    DocumentChunkSerializer, DocumentDetailSerializer, DocumentSerializer,
    DocumentUploadSerializer, HealthSerializer, KnowledgeBaseSerializer,
    MessageSerializer, PromptTemplateSerializer, SearchHitSerializer,
    SearchRequestSerializer, TagSerializer,
)

logger = logging.getLogger(__name__)
_pipeline  = DocumentPipelineService()
_retriever = RetrievalService()
_ollama    = OllamaClient()


# ── Permissions ───────────────────────────────────────────────────────────────

class IsAuthenticatedOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        return request.user and request.user.is_authenticated


# ── Health Check ──────────────────────────────────────────────────────────────

class HealthCheckView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        ollama_online = _ollama.is_online()
        try:
            store = VectorStoreFactory.get()
            vs_healthy = store.health_check()
            total_chunks = store.count()
        except Exception:
            vs_healthy   = False
            total_chunks = 0

        data = {
            "status":               "ok" if ollama_online and vs_healthy else "degraded",
            "ollama_online":        ollama_online,
            "vector_store_healthy": vs_healthy,
            "total_documents":      Document.objects.filter(is_deleted=False).count(),
            "total_chunks":         total_chunks,
            "version":              "1.0.0-phase7",
        }
        return Response(data)


# ── Knowledge Bases ───────────────────────────────────────────────────────────

class KnowledgeBaseViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = KnowledgeBaseSerializer
    queryset = KnowledgeBase.objects.filter(
        is_active=True, is_deleted=False
    ).order_by("name")


# ── Documents ─────────────────────────────────────────────────────────────────

class DocumentViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Document.objects.filter(
            is_deleted=False
        ).select_related("knowledge_base").order_by("-created_at")
        kb = self.request.query_params.get("kb")
        status_f = self.request.query_params.get("status")
        q = self.request.query_params.get("q")
        if kb:
            qs = qs.filter(knowledge_base_id=kb)
        if status_f:
            qs = qs.filter(status=status_f)
        if q:
            qs = qs.filter(title__icontains=q)
        return qs

    def get_serializer_class(self):
        if self.action == "retrieve":
            return DocumentDetailSerializer
        return DocumentSerializer

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        doc = self.get_object()
        return Response({
            "status":       doc.status,
            "status_label": doc.get_status_display(),
            "is_indexed":   doc.is_indexed,
            "failed":       doc.failed,
            "page_count":   doc.page_count,
            "word_count":   doc.word_count,
        })

    @action(detail=True, methods=["get"])
    def chunks(self, request, pk=None):
        doc = self.get_object()
        chunks = DocumentChunk.objects.filter(
            document=doc
        ).order_by("chunk_index")
        serializer = DocumentChunkSerializer(chunks, many=True)
        return Response(serializer.data)


# ── Upload ────────────────────────────────────────────────────────────────────

class DocumentUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def post(self, request):
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST
            )

        kb_id = request.data.get("knowledge_base")
        try:
            kb = KnowledgeBase.objects.get(pk=kb_id, is_active=True)
        except (KnowledgeBase.DoesNotExist, TypeError, ValueError):
            return Response(
                {"error": "Invalid knowledge_base id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        valid, err = validate_upload(file_obj, file_obj.name)
        if not valid:
            return Response({"error": err}, status=status.HTTP_400_BAD_REQUEST)

        try:
            doc = _pipeline.ingest(
                file_obj=file_obj,
                filename=file_obj.name,
                knowledge_base=kb,
                uploaded_by=request.user,
            )
            return Response(
                DocumentSerializer(doc).data, status=status.HTTP_201_CREATED
            )
        except DuplicateDocumentError as e:
            return Response(
                {"error": "Duplicate file.", "existing_id": e.existing_doc.pk},
                status=status.HTTP_409_CONFLICT,
            )
        except UnsupportedFileTypeError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("API upload error")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ── Search ────────────────────────────────────────────────────────────────────

class SearchView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        ser = SearchRequestSerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            result = _retriever.retrieve(
                query=d["q"],
                top_k=d["top_k"],
                knowledge_base_id=d.get("knowledge_base_id"),
                similarity_threshold=d["threshold"],
                user=request.user,
            )
        except OllamaError as e:
            return Response(
                {"error": f"Ollama unavailable: {e}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        hits = SearchHitSerializer(result.chunks, many=True).data
        return Response({
            "query":          d["q"],
            "total_results":  len(result.chunks),
            "embedding_ms":   round(result.embedding_time_ms, 1),
            "search_ms":      round(result.search_time_ms, 1),
            "results":        hits,
        })


# ── Chat ──────────────────────────────────────────────────────────────────────

class ConversationViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    http_method_names  = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Conversation.objects.filter(
            user=self.request.user, is_deleted=False
        ).order_by("-last_message_at")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ConversationDetailSerializer
        return ConversationSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"])
    def chat(self, request, pk=None):
        """Send a message and get an AI answer within this conversation."""
        conv = self.get_object()
        ser  = ChatRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        question = ser.validated_data["question"]

        try:
            answer = rag_agent.ask(
                question=question,
                conversation=conv,
                user=request.user,
                knowledge_base_id=conv.knowledge_base_id,
            )
        except OllamaError as e:
            return Response(
                {"error": f"Ollama unavailable: {e}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            logger.exception("API chat error")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({
            "answer":            answer.text,
            "is_fallback":       answer.is_fallback,
            "model_used":        answer.model_used,
            "generation_ms":     round(answer.generation_time_ms, 0),
            "prompt_tokens":     answer.prompt_tokens,
            "completion_tokens": answer.completion_tokens,
            "chunks_used":       answer.chunks_used,
            "sources": [
                {
                    "rank":             s.rank,
                    "document_title":   s.document_title,
                    "page_number":      s.page_number,
                    "paragraph_number": s.paragraph_number,
                    "score":            s.display_score,
                }
                for s in answer.sources
            ],
        })

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        """Export conversation as JSON or plain text."""
        conv     = self.get_object()
        fmt      = request.query_params.get("format", "json")
        messages = Message.objects.filter(
            conversation=conv, is_deleted=False
        ).order_by("sequence")

        if fmt == "txt":
            from django.http import HttpResponse
            lines = [
                f"KB Platform — Conversation Export",
                f"Title:   {conv.title or 'Untitled'}",
                f"Date:    {conv.created_at:%Y-%m-%d %H:%M}",
                f"KB:      {conv.knowledge_base.name if conv.knowledge_base else 'All'}",
                "=" * 60,
                "",
            ]
            for msg in messages:
                prefix = "You" if msg.role == "user" else "AI"
                lines.append(f"[{prefix}]  {msg.content}")
                lines.append("")
            return HttpResponse(
                "\n".join(lines),
                content_type="text/plain; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="conv_{pk}.txt"'
                },
            )

        # JSON export (default)
        return Response(ConversationDetailSerializer(conv).data)


# ── Chat (stateless — creates its own conversation) ───────────────────────────

class ChatView(APIView):
    """
    Stateless chat endpoint. Creates a new conversation per call unless
    conversation_id is supplied.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ser = ChatRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        conv_id = d.get("conversation_id")
        conv    = None
        if conv_id:
            try:
                conv = Conversation.objects.get(
                    pk=conv_id, user=request.user, is_deleted=False
                )
            except Conversation.DoesNotExist:
                return Response(
                    {"error": "Conversation not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            conv = Conversation.objects.create(
                user=request.user,
                knowledge_base_id=d.get("knowledge_base_id"),
            )

        try:
            answer = rag_agent.ask(
                question=d["question"],
                conversation=conv,
                user=request.user,
                knowledge_base_id=d.get("knowledge_base_id") or conv.knowledge_base_id,
            )
        except OllamaError as e:
            return Response(
                {"error": f"Ollama unavailable: {e}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            logger.exception("Stateless chat error")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({
            "conversation_id":   conv.pk,
            "answer":            answer.text,
            "is_fallback":       answer.is_fallback,
            "model_used":        answer.model_used,
            "generation_ms":     round(answer.generation_time_ms, 0),
            "sources": [
                {
                    "rank":           s.rank,
                    "document_title": s.document_title,
                    "page_number":    s.page_number,
                    "score":          s.display_score,
                }
                for s in answer.sources
            ],
        }, status=status.HTTP_201_CREATED)


# ── Embedding / OCR status ────────────────────────────────────────────────────

class EmbeddingStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        doc_id = request.query_params.get("document_id")
        qs     = DocumentChunk.objects.filter(is_deleted=False)
        if doc_id:
            qs = qs.filter(document_id=doc_id)
        total    = qs.count()
        embedded = qs.filter(is_embedded=True).count()
        return Response({
            "document_id":     doc_id,
            "total_chunks":    total,
            "embedded_chunks": embedded,
            "pending_chunks":  total - embedded,
            "pct_complete":    round((embedded / total * 100) if total else 0, 1),
        })


class OCRStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        doc_id = request.query_params.get("document_id")
        if not doc_id:
            return Response({"error": "document_id required"}, status=400)
        try:
            job = OCRJob.objects.get(document_id=doc_id)
            return Response({
                "status":             job.status,
                "pages_processed":    job.pages_processed,
                "pages_failed":       job.pages_failed,
                "average_confidence": job.average_confidence,
                "duration_seconds":   job.duration_seconds,
                "error_message":      job.error_message,
            })
        except OCRJob.DoesNotExist:
            return Response({"error": "No OCR job found for this document."}, status=404)


# ── Settings (staff only) ─────────────────────────────────────────────────────

class SettingsView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        settings_qs = PlatformSetting.objects.filter(
            is_editable=True
        ).select_related("category").order_by("category__order", "key")
        return Response([
            {
                "key":         s.key,
                "value":       "***" if s.is_sensitive else s.value,
                "data_type":   s.data_type,
                "description": s.description,
                "category":    s.category.name if s.category else None,
            }
            for s in settings_qs
        ])

    def patch(self, request):
        updates = request.data  # {"key": "value", ...}
        if not isinstance(updates, dict):
            return Response({"error": "Expected a JSON object."}, status=400)
        results = {}
        for key, value in updates.items():
            try:
                setting = PlatformSetting.objects.get(key=key, is_editable=True)
                setting.value = str(value)
                setting.modified_by = request.user
                setting.save(update_fields=["value", "modified_by", "modified_at"])
                results[key] = "updated"
            except PlatformSetting.DoesNotExist:
                results[key] = "not_found"
        return Response(results)


# ── AI Models (staff only) ────────────────────────────────────────────────────

class AIModelViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    serializer_class   = AIModelSerializer
    queryset = AIModel.objects.filter(is_active=True).order_by("model_type", "name")


# ── Users (staff only) ───────────────────────────────────────────────────────

class UserListView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        users = User.objects.all().order_by("username").values(
            "id", "username", "email", "first_name", "last_name",
            "is_active", "is_staff", "date_joined", "last_login",
        )
        return Response(list(users))
