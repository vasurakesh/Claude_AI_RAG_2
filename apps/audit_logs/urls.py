from django.urls import path
from . import views

app_name = "audit_logs"
urlpatterns = [
    path("", views.list_view, name="list"),
]
