from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import KnowledgeBase, Tag


@login_required
def list_view(request):
    kbs = KnowledgeBase.objects.filter(is_deleted=False).order_by('name')
    return render(request, 'knowledge_base/list.html', {'knowledge_bases': kbs})
