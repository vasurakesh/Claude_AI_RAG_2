"""
apps/audit_logs/views.py
"""
import logging
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.shortcuts import render
from .models import AuditLog

logger = logging.getLogger(__name__)
is_staff = user_passes_test(lambda u: u.is_staff)


@login_required
@is_staff
def list_view(request):
    qs = AuditLog.objects.select_related("user").order_by("-created_at")

    action_type = request.GET.get("action_type", "")
    username    = request.GET.get("username", "")
    date_from   = request.GET.get("date_from", "")
    date_to     = request.GET.get("date_to", "")

    if action_type:
        qs = qs.filter(action_type=action_type)
    if username:
        qs = qs.filter(user__username__icontains=username)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "audit_logs/list.html", {
        "page_obj":     page,
        "action_types": AuditLog.ActionType.choices,
        "filters": {
            "action_type": action_type,
            "username":    username,
            "date_from":   date_from,
            "date_to":     date_to,
        },
        "total": qs.count(),
    })
