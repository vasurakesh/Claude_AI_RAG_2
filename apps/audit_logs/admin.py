from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action_type", "object_repr", "ip_address", "duration_ms")
    list_filter = ("action_type",)
    search_fields = ("user__username", "description", "object_repr", "ip_address")
    readonly_fields = (
        "user", "created_at", "action_type", "description",
        "content_type", "object_id", "object_repr",
        "before_state", "after_state",
        "ip_address", "user_agent", "request_path",
        "duration_ms", "extra_data",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False  # Audit logs are system-generated only

    def has_change_permission(self, request, obj=None):
        return False  # Immutable

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser  # Only superuser can purge
