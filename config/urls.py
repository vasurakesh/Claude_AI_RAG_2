from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

admin.site.site_header = "Knowledge Management AI Platform"
admin.site.site_title  = "KB Platform Admin"
admin.site.index_title = "Platform Administration"

urlpatterns = [
    path('api/v1/', include('apiroutes.urls')),
    path('admin/',        admin.site.urls),
    path('',              include('apps.dashboard.urls')),
    path('auth/',         include('apps.authentication.urls')),
    path('kb/',           include('apps.knowledge_base.urls')),
    path('documents/',    include('apps.document_upload.urls')),
    path('search/',       include('apps.vector_search.urls')),
    path('chat/',         include('apps.chat.urls')),
    path('settings/',     include('apps.settings_app.urls')),
    path('audit-logs/',   include('apps.audit_logs.urls')),
    path('ai/',           include('apps.ai_agent.urls')),
    path('embeddings/',   include('apps.embedding_service.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
