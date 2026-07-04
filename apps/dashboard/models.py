"""
apps/dashboard/models.py
~~~~~~~~~~~~~~~~~~~~~~~~~
DashboardWidget - user-configurable dashboard layout.

The dashboard itself is mostly read-only aggregations pulled from the other
apps. This model stores each user's widget arrangement so preferences
persist across sessions.
"""

from django.db import models
from django.contrib.auth.models import User
from core.models import TimeStampedModel


class DashboardWidget(TimeStampedModel):
    """
    Tracks which widgets a user has enabled and their layout order.
    Widget rendering happens in the template / view layer.
    """

    class WidgetType(models.TextChoices):
        DOCUMENT_STATS    = "document_stats",    "Document Statistics"
        RECENT_UPLOADS    = "recent_uploads",    "Recent Uploads"
        INDEXING_QUEUE    = "indexing_queue",    "Indexing Queue"
        RECENT_SEARCHES   = "recent_searches",   "Recent Searches"
        RECENT_CHATS      = "recent_chats",      "Recent Conversations"
        SYSTEM_HEALTH     = "system_health",     "System Health"
        MODEL_STATUS      = "model_status",      "Model Status"
        STORAGE_USAGE     = "storage_usage",     "Storage Usage"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="dashboard_widgets",
        db_index=True,
    )
    widget_type = models.CharField(
        max_length=30,
        choices=WidgetType.choices,
    )
    is_enabled = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Widget-specific configuration (e.g. row count to display)",
    )

    class Meta:
        db_table = "dashboard_widget"
        ordering = ["user", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "widget_type"],
                name="uq_widget_user_type",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user.username}: {self.get_widget_type_display()}"
