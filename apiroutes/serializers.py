"""
apiroutes/serializers.py
~~~~~~~~~~~~~~~~~~~~~~~~~
DRF serializers for every public API endpoint.
"""
from django.contrib.auth.models import User
from rest_framework import serializers

from apps.document_upload.models import Document, DocumentPage
from apps.embedding_service.models import DocumentChunk, EmbeddingRecord
from apps.knowledge_base.models import KnowledgeBase, Tag
from apps.chat.models import Conversation, Message, MessageChunkCitation
from apps.vector_search.models import SearchQuery, SearchResult
from apps.ai_agent.models import AIModel, PromptTemplate, AgentConfig


# ── Knowledge Base ────────────────────────────────────────────────────────────

class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "slug", "color"]


class KnowledgeBaseSerializer(serializers.ModelSerializer):
    document_count = serializers.SerializerMethodField()

    class Meta:
        model = KnowledgeBase
        fields = ["id", "name", "slug", "description", "is_active",
                  "document_count", "created_at"]
        read_only_fields = ["id", "created_at", "document_count"]

    def get_document_count(self, obj):
        return obj.documents.filter(is_deleted=False).count()


# ── Documents ─────────────────────────────────────────────────────────────────

class DocumentPageSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentPage
        fields = ["page_number", "raw_text", "is_ocr", "ocr_confidence", "word_count"]


class DocumentSerializer(serializers.ModelSerializer):
    knowledge_base_name = serializers.CharField(
        source="knowledge_base.name", read_only=True
    )
    tags = TagSerializer(many=True, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    file_category_label = serializers.CharField(
        source="get_file_category_display", read_only=True
    )

    class Meta:
        model = Document
        fields = [
            "id", "title", "original_filename", "file_size", "mime_type",
            "extension", "file_category", "file_category_label",
            "sha256_hash", "knowledge_base", "knowledge_base_name",
            "tags", "status", "status_label",
            "page_count", "word_count", "language", "author",
            "requires_ocr", "ocr_completed",
            "processing_error", "processing_started_at", "processing_completed_at",
            "created_at", "modified_at",
        ]
        read_only_fields = fields


class DocumentDetailSerializer(DocumentSerializer):
    pages = DocumentPageSerializer(many=True, read_only=True)

    class Meta(DocumentSerializer.Meta):
        fields = DocumentSerializer.Meta.fields + ["pages"]


# ── Upload ────────────────────────────────────────────────────────────────────

class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    knowledge_base = serializers.PrimaryKeyRelatedField(
        queryset=KnowledgeBase.objects.filter(is_active=True, is_deleted=False)
    )
    tags = serializers.CharField(required=False, default="")
    process_now = serializers.BooleanField(default=True)


# ── Chunks ────────────────────────────────────────────────────────────────────

class DocumentChunkSerializer(serializers.ModelSerializer):
    document_title = serializers.CharField(source="document.title", read_only=True)

    class Meta:
        model = DocumentChunk
        fields = [
            "id", "chunk_id", "document", "document_title",
            "chunk_index", "text", "token_count",
            "page_number", "paragraph_number",
            "strategy_used", "is_embedded", "created_at",
        ]
        read_only_fields = fields


# ── Search ────────────────────────────────────────────────────────────────────

class SearchRequestSerializer(serializers.Serializer):
    q = serializers.CharField(min_length=1, max_length=2000)
    knowledge_base_id = serializers.IntegerField(required=False, allow_null=True)
    top_k = serializers.IntegerField(default=5, min_value=1, max_value=20)
    threshold = serializers.FloatField(default=0.0, min_value=0.0, max_value=1.0)


class SearchHitSerializer(serializers.Serializer):
    rank = serializers.IntegerField()
    score = serializers.FloatField()
    document_id = serializers.IntegerField(source="chunk.document_id")
    document_title = serializers.CharField(source="chunk.document.title")
    chunk_id = serializers.UUIDField(source="chunk.chunk_id")
    page_number = serializers.IntegerField(source="chunk.page_number")
    paragraph_number = serializers.IntegerField(source="chunk.paragraph_number")
    text_preview = serializers.SerializerMethodField()

    def get_text_preview(self, obj):
        return obj.chunk.text[:400]


# ── Chat ──────────────────────────────────────────────────────────────────────

class MessageCitationSerializer(serializers.ModelSerializer):
    document_title = serializers.CharField(
        source="chunk.document.title", read_only=True
    )
    page_number = serializers.IntegerField(
        source="chunk.page_number", read_only=True
    )

    class Meta:
        model = MessageChunkCitation
        fields = [
            "rank", "similarity_score", "rerank_score",
            "document_title", "page_number", "included_in_context",
        ]


class MessageSerializer(serializers.ModelSerializer):
    citations = MessageCitationSerializer(many=True, read_only=True)
    model_name = serializers.CharField(
        source="model_used.name", read_only=True, default=None
    )

    class Meta:
        model = Message
        fields = [
            "id", "role", "content", "sequence",
            "model_name", "prompt_tokens", "completion_tokens",
            "generation_time_ms", "is_fallback_response",
            "citations", "created_at",
        ]
        read_only_fields = fields


class ConversationSerializer(serializers.ModelSerializer):
    knowledge_base_name = serializers.CharField(
        source="knowledge_base.name", read_only=True, default=None
    )
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Conversation
        fields = [
            "id", "title", "username", "knowledge_base",
            "knowledge_base_name", "is_pinned",
            "message_count", "last_message_at", "created_at",
        ]
        read_only_fields = fields


class ConversationDetailSerializer(ConversationSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta(ConversationSerializer.Meta):
        fields = ConversationSerializer.Meta.fields + ["messages"]


class ChatRequestSerializer(serializers.Serializer):
    question = serializers.CharField(min_length=1, max_length=4000)
    conversation_id = serializers.IntegerField(required=False, allow_null=True)
    knowledge_base_id = serializers.IntegerField(required=False, allow_null=True)


# ── AI Agent ──────────────────────────────────────────────────────────────────

class AIModelSerializer(serializers.ModelSerializer):
    model_type_label = serializers.CharField(
        source="get_model_type_display", read_only=True
    )

    class Meta:
        model = AIModel
        fields = [
            "id", "name", "display_name", "model_type", "model_type_label",
            "is_active", "is_default", "context_window", "vector_dimensions",
        ]


class PromptTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromptTemplate
        fields = [
            "id", "name", "template_type", "template_text",
            "is_active", "is_default", "version",
        ]


class AgentConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentConfig
        fields = [
            "id", "name", "is_active",
            "llm_model", "embedding_model",
            "top_k", "similarity_threshold", "max_context_tokens",
            "enable_reranking", "temperature", "top_p", "top_k_llm", "max_tokens",
        ]


# ── Health ────────────────────────────────────────────────────────────────────

class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    ollama_online = serializers.BooleanField()
    vector_store_healthy = serializers.BooleanField()
    total_documents = serializers.IntegerField()
    total_chunks = serializers.IntegerField()
    version = serializers.CharField()
