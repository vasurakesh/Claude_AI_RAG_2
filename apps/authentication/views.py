"""
apps/authentication/views.py
"""
import logging
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
from .models import UserProfile

logger = logging.getLogger(__name__)


@csrf_protect
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard:index')
    
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        login(request, user)
        logger.info("User %s logged in from %s", user.username, request.META.get('REMOTE_ADDR'))
        next_url = request.POST.get('next') or request.GET.get('next') or 'dashboard:index'
        return redirect(next_url)
    
    return render(request, 'authentication/login.html', {'form': form})


@require_POST
def logout_view(request):
    username = request.user.username
    logout(request)
    logger.info("User %s logged out", username)
    return redirect('authentication:login')


@login_required
def profile_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        profile.theme = request.POST.get('theme', 'light')
        profile.bio = request.POST.get('bio', '')
        profile.save()
        messages.success(request, 'Profile updated successfully.')
        return redirect('authentication:profile')
    return render(request, 'authentication/profile.html', {'profile': profile})


@login_required
def password_change_view(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, 'Password changed successfully.')
        return redirect('authentication:profile')
    return render(request, 'authentication/password_change.html', {'form': form})


@login_required
@require_POST
def set_theme_view(request):
    """AJAX endpoint — saves dark/light preference to UserProfile."""
    import json
    try:
        data = json.loads(request.body)
        theme = data.get('theme', 'light')
        if theme not in ('light', 'dark'):
            return JsonResponse({'error': 'Invalid theme'}, status=400)
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.theme = theme
        profile.save(update_fields=['theme'])
        return JsonResponse({'status': 'ok', 'theme': theme})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
