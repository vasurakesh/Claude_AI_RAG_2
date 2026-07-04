from django.urls import path
from . import views
app_name = 'knowledge_base'
urlpatterns = [
    path('', views.list_view, name='list'),
]
