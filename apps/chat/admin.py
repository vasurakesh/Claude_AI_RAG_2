from django.contrib import admin
from .models import Conversation, Message, MessageChunkCitation, ConversationContext


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ("role", "sequence", "model_used", "prompt_tokens", "completion_tokens", "generation_time_ms", "created_at")
    fields = ("sequence", "role", "content", "model_used", "generation_time_ms", "is_fallback_response")
    ordering = ("sequence",)
    can_delete = False
    show_change_link = True


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "knowledge_base", "message_count", "is_pinned", "last_message_at", "created_at")
    list_filter = ("is_pinned", "knowledge_base")
    search_fields = ("title", "user__username")
    readonly_fields = ("message_count", "last_message_at", "created_at", "modified_at")
    inlines = [MessageInline]
    date_hierarchy = "created_at"


class MessageChunkCitationInline(admin.TabularInline):
    model = MessageChunkCitation
    extra = 0
    readonly_fields = ("chunk", "rank", "similarity_score", "rerank_score", "included_in_context")
    can_delete = False


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "role", "sequence", "model_used", "prompt_tokens", "completion_tokens", "generation_time_ms", "is_fallback_response")
    list_filter = ("role", "is_fallback_response")
    search_fields = ("content", "conversation__user__username")
    readonly_fields = ("created_at", "modified_at")
    inlines = [MessageChunkCitationInline]


@admin.register(ConversationContext)
class ConversationContextAdmin(admin.ModelAdmin):
    list_display = ("message", "token_count", "chunks_used", "created_at")
    readonly_fields = ("created_at", "modified_at")
