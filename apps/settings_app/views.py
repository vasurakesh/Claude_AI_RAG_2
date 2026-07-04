"""
apps/settings_app/views.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Platform settings admin panel — grouped key/value editor.
"""
import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.ai_agent.models import AIModel, AgentConfig
from core.embeddings.chunkers import ChunkerFactory
from .models import PlatformSetting, SettingCategory

logger = logging.getLogger(__name__)
is_staff = user_passes_test(lambda u: u.is_staff)


@login_required
@is_staff
def index_view(request):
    categories = SettingCategory.objects.prefetch_related(
        "settings"
    ).order_by("order", "name")
    ai_models      = AIModel.objects.filter(is_active=True).order_by("model_type", "name")
    agent_config   = AgentConfig.objects.filter(is_active=True).first()
    chunking_strats = ChunkerFactory.strategies()

    return render(request, "settings_app/index.html", {
        "categories":      categories,
        "ai_models":       ai_models,
        "agent_config":    agent_config,
        "chunking_strats": chunking_strats,
    })


@login_required
@is_staff
@require_POST
def save_setting_view(request):
    key   = request.POST.get("key", "").strip()
    value = request.POST.get("value", "").strip()
    if not key:
        messages.error(request, "Setting key is required.")
        return redirect("settings_app:index")
    try:
        setting = PlatformSetting.objects.get(key=key, is_editable=True)
        setting.value       = value
        setting.modified_by = request.user
        setting.save(update_fields=["value", "modified_by", "modified_at"])
        messages.success(request, f"Setting '{key}' updated.")
    except PlatformSetting.DoesNotExist:
        messages.error(request, f"Setting '{key}' not found or is read-only.")
    return redirect("settings_app:index")


@login_required
@is_staff
@require_POST
def save_agent_config_view(request):
    cfg = AgentConfig.objects.filter(is_active=True).first()
    if not cfg:
        messages.error(request, "No active agent configuration found.")
        return redirect("settings_app:index")
    try:
        cfg.top_k               = int(request.POST.get("top_k", cfg.top_k))
        cfg.similarity_threshold = float(request.POST.get("similarity_threshold", cfg.similarity_threshold))
        cfg.max_context_tokens  = int(request.POST.get("max_context_tokens", cfg.max_context_tokens))
        cfg.temperature         = float(request.POST.get("temperature", cfg.temperature))
        cfg.top_p               = float(request.POST.get("top_p", cfg.top_p))
        cfg.top_k_llm           = int(request.POST.get("top_k_llm", cfg.top_k_llm))
        cfg.max_tokens          = int(request.POST.get("max_tokens", cfg.max_tokens))
        cfg.enable_reranking    = request.POST.get("enable_reranking") == "on"

        llm_id = request.POST.get("llm_model")
        emb_id = request.POST.get("embedding_model")
        if llm_id:
            cfg.llm_model = AIModel.objects.filter(pk=llm_id).first()
        if emb_id:
            cfg.embedding_model = AIModel.objects.filter(pk=emb_id).first()

        cfg.modified_by = request.user
        cfg.save()
        messages.success(request, "Agent configuration saved.")
    except (ValueError, TypeError) as e:
        messages.error(request, f"Invalid value: {e}")
    return redirect("settings_app:index")
