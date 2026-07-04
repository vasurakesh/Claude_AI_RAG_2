"""Stub views for apps.ai_agent — fully implemented in later phases."""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required

@login_required
def index(request):
    return render(request, 'base/coming_soon.html', {'app': 'ai_agent'})
