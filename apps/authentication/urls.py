from django.urls import path
from . import views

app_name = 'authentication'

urlpatterns = [
    path('login/',            views.login_view,          name='login'),
    path('logout/',           views.logout_view,         name='logout'),
    path('profile/',          views.profile_view,        name='profile'),
    path('password/change/',  views.password_change_view, name='password_change'),
    path('set-theme/',        views.set_theme_view,      name='set_theme'),
]
