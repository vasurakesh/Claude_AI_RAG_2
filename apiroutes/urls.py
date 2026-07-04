"""
apiroutes/urls.py
~~~~~~~~~~~~~~~~~~
REST API router — all endpoints under /api/v1/
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"knowledge-bases", views.KnowledgeBaseViewSet, basename="kb")
router.register(r"documents",       views.DocumentViewSet,       basename="document")
router.register(r"conversations",   views.ConversationViewSet,   basename="conversation")
router.register(r"ai-models",       views.AIModelViewSet,        basename="aimodel")

urlpatterns = [
    # Router-registered ViewSets
    path("", include(router.urls)),

    # Standalone endpoints
    path("health/",         views.HealthCheckView.as_view(),    name="api-health"),
    path("upload/",         views.DocumentUploadView.as_view(), name="api-upload"),
    path("search/",         views.SearchView.as_view(),         name="api-search"),
    path("chat/",           views.ChatView.as_view(),           name="api-chat"),
    path("settings/",       views.SettingsView.as_view(),       name="api-settings"),
    path("users/",          views.UserListView.as_view(),       name="api-users"),
    path("embedding/status/", views.EmbeddingStatusView.as_view(), name="api-emb-status"),
    path("ocr/status/",     views.OCRStatusView.as_view(),      name="api-ocr-status"),

    # DRF browsable API auth
    path("auth/",           include("rest_framework.urls")),
]
