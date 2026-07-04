from django.contrib import admin
from .models import AIModel, PromptTemplate, AgentConfig


@admin.register(AIModel)
class AIModelAdmin(admin.ModelAdmin):
    list_display = ("display_name", "name", "model_type", "is_active", "is_default", "context_window", "vector_dimensions")
    list_filter = ("model_type", "is_active", "is_default")
    search_fields = ("name", "display_name")
    readonly_fields = ("created_at", "modified_at")
    fieldsets = (
        ("Model Identity", {"fields": ("name", "display_name", "model_type", "ollama_url")}),
        ("Configuration", {"fields": ("context_window", "vector_dimensions", "is_active", "is_default")}),
        ("Notes", {"fields": ("notes",)}),
        ("Audit", {"fields": ("created_at", "modified_at"), "classes": ("collapse",)}),
    )


@admin.register(PromptTemplate)
class PromptTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "template_type", "version", "is_active", "is_default")
    list_filter = ("template_type", "is_active", "is_default")
    search_fields = ("name", "template_text")
    readonly_fields = ("created_at", "modified_at")


@admin.register(AgentConfig)
class AgentConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "top_k", "temperature", "max_tokens", "enable_reranking")
    list_filter = ("is_active",)
    readonly_fields = ("created_at", "modified_at")
    fieldsets = (
        ("Identity", {"fields": ("name", "is_active")}),
        ("Models", {"fields": ("llm_model", "embedding_model")}),
        ("Retrieval", {"fields": ("top_k", "similarity_threshold", "max_context_tokens", "enable_reranking")}),
        ("LLM Parameters", {"fields": ("temperature", "top_p", "top_k_llm", "max_tokens")}),
        ("Prompts", {"fields": ("rag_prompt",)}),
    )
