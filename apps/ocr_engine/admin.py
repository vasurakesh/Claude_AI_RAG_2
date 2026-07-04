from django.contrib import admin
from .models import OCRJob, OCRPageResult


class OCRPageResultInline(admin.TabularInline):
    model = OCRPageResult
    extra = 0
    readonly_fields = ("page_number", "confidence", "duration_seconds", "error_message")
    fields = ("page_number", "confidence", "duration_seconds", "error_message")
    can_delete = False


@admin.register(OCRJob)
class OCRJobAdmin(admin.ModelAdmin):
    list_display = ("document", "status", "engine", "pages_processed", "pages_failed", "average_confidence", "created_at")
    list_filter = ("status", "engine")
    search_fields = ("document__title",)
    readonly_fields = ("started_at", "completed_at", "duration_seconds", "pages_processed", "pages_failed", "average_confidence", "error_message", "created_at")
    inlines = [OCRPageResultInline]


@admin.register(OCRPageResult)
class OCRPageResultAdmin(admin.ModelAdmin):
    list_display = ("job", "page_number", "confidence", "duration_seconds")
    search_fields = ("job__document__title",)
    readonly_fields = ("created_at",)
