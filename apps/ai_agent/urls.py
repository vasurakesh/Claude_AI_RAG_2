from django.urls import path
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt


@require_GET
def health_check(request):
    """
    Checks Ollama connectivity.  Phase 6 wires the full agent; this stub
    already gives the dashboard a real online/offline signal.
    """
    try:
        from core.ai.ollama_client import ollama_client
        online = ollama_client.is_online()
        models = []
        if online:
            try:
                raw = ollama_client.list_models()
                models = [m.get("name", "") for m in raw]
            except Exception:
                pass
        return JsonResponse({
            "ollama_online": online,
            "models": models,
            "message": "Ollama is running" if online else "Ollama is offline — start it with: ollama serve",
        })
    except Exception as e:
        return JsonResponse({"ollama_online": False, "message": str(e)})


app_name = 'ai_agent'
urlpatterns = [
    path('health/', health_check, name='health_check'),
]
