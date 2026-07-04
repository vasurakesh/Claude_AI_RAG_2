from django.urls import path
from . import views

app_name = "settings_app"
urlpatterns = [
    path("",             views.index_view,            name="index"),
    path("save/",        views.save_setting_view,     name="save"),
    path("agent/save/",  views.save_agent_config_view, name="save_agent"),
]
