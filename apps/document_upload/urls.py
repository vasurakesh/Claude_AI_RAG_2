from django.urls import path
from . import views

app_name = 'document_upload'

urlpatterns = [
    path('',                views.list_view,   name='list'),
    path('upload/',         views.upload_view, name='upload'),
    path('<int:pk>/',       views.detail_view, name='detail'),
    path('<int:pk>/delete/', views.delete_view, name='delete'),
    path('<int:pk>/status/', views.status_view, name='status'),
]
