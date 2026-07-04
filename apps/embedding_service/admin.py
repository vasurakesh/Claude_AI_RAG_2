from django.contrib import admin
from .models import DocumentChunk, EmbeddingRecord


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ("document", "chunk_index", "page_number", "token_count", "strategy_used", "is_embedded")
    list_filter = ("strategy_used", "is_embedded")
    search_fields = ("document__title", "text")
    readonly_fields = ("chunk_id", "created_at", "modified_at")
    date_hierarchy = "created_at"


@admin.register(EmbeddingRecord)
class EmbeddingRecordAdmin(admin.ModelAdmin):
    list_display = ("chunk", "model_name", "vector_dimensions", "generation_time_ms", "created_at")
    list_filter = ("model_name",)
    search_fields = ("chunk__document__title", "vector_id")
    readonly_fields = ("vector_id", "created_at", "modified_at")
