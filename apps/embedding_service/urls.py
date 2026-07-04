from django.urls import path
from . import views

app_name = 'embedding_service'
urlpatterns = [
    path('document/<int:doc_pk>/chunks/', views.chunk_list_view, name='chunk_list'),
    path('document/<int:doc_pk>/reindex/', views.reindex_view,   name='reindex'),
    path('stats/',                         views.vector_store_stats_view, name='stats'),
]
