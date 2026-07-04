from django.urls import path
from . import views

app_name = "vector_search"
urlpatterns = [
    path("", views.search_view, name="search"),
]
