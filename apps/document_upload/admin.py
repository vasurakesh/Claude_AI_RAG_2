from django.contrib import admin
from .models import Document, DocumentPage


class DocumentPageInline(admin.TabularInline):
    model = DocumentPage
    extra = 0
    readonly_fields = ("page_number", "word_count", "is_ocr", "ocr_confidence")
    fields = ("page_number", "is_ocr", "ocr_confidence", "word_count")
    show_change_link = True
    can_delete = False


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "knowledge_base", "status", "file_category", "file_size", "requires_ocr", "created_at")
    list_filter = ("status", "file_category", "requires_ocr", "ocr_completed", "knowledge_base")
    search_fields = ("title", "original_filename", "sha256_hash")
    readonly_fields = (
        "sha256_hash", "file_size", "mime_type", "extension",
        "page_count", "word_count", "processing_started_at",
        "processing_completed_at", "processing_error",
        "created_at", "modified_at",
    )
    inlines = [DocumentPageInline]
    date_hierarchy = "created_at"
    fieldsets = (
        ("File Info", {"fields": ("title", "original_filename", "file", "file_size", "mime_type", "extension", "file_category", "sha256_hash")}),
        ("Organisation", {"fields": ("knowledge_base", "tags", "parent_document")}),
        ("Pipeline", {"fields": ("status", "requires_ocr", "ocr_completed", "processing_started_at", "processing_completed_at", "processing_error")}),
        ("Extracted Metadata", {"fields": ("page_count", "word_count", "language", "author", "doc_created_at", "doc_modified_at")}),
        ("Audit", {"fields": ("created_at", "modified_at", "created_by", "modified_by", "is_deleted", "deleted_at"), "classes": ("collapse",)}),
    )


@admin.register(DocumentPage)
class DocumentPageAdmin(admin.ModelAdmin):
    list_display = ("document", "page_number", "is_ocr", "ocr_confidence", "word_count")
    list_filter = ("is_ocr",)
    search_fields = ("document__title",)
    readonly_fields = ("created_at", "modified_at")
