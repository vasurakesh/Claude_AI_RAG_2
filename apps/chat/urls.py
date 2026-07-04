from django.urls import path
from . import views

app_name = "chat"

urlpatterns = [
    path("",                              views.index_view,              name="index"),
    path("new/",                          views.new_conversation_view,   name="new"),
    path("<int:pk>/",                     views.conversation_view,       name="conversation"),
    path("<int:pk>/send/",                views.send_message_view,       name="send"),
    path("<int:pk>/rename/",              views.rename_conversation_view, name="rename"),
    path("<int:pk>/delete/",              views.delete_conversation_view, name="delete"),
    path("<int:pk>/history/",             views.message_history_view,    name="history"),
]
