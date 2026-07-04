from django.contrib import admin
from .models import SearchQuery, SearchResult


class SearchResultInline(admin.TabularInline):
    model = SearchResult
    extra = 0
    readonly_fields = ("chunk", "rank", "similarity_score", "rerank_score", "used_in_context")
    can_delete = False


@admin.register(SearchQuery)
class SearchQueryAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "query_text_short", "total_results", "embedding_time_ms", "search_time_ms", "created_at")
    list_filter = ("query_embedding_model", "knowledge_base")
    search_fields = ("query_text", "user__username")
    readonly_fields = ("created_at", "modified_at")
    inlines = [SearchResultInline]
    date_hierarchy = "created_at"

    @admin.display(description="Query")
    def query_text_short(self, obj):
        return obj.query_text[:80]


@admin.register(SearchResult)
class SearchResultAdmin(admin.ModelAdmin):
    list_display = ("query", "rank", "similarity_score", "rerank_score", "used_in_context")
    list_filter = ("used_in_context",)
