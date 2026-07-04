from django.contrib import admin
from .models import DashboardWidget


@admin.register(DashboardWidget)
class DashboardWidgetAdmin(admin.ModelAdmin):
    list_display = ("user", "widget_type", "position", "is_enabled")
    list_filter = ("widget_type", "is_enabled")
    search_fields = ("user__username",)
    readonly_fields = ("created_at", "modified_at")
