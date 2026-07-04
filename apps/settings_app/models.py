"""
apps/settings_app/models.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
PlatformSetting - a key/value config store managed from Django Admin.

Design decisions:
- A flat key/value table (with a typed 'data_type' column) gives admins
  full control over all runtime settings without a code deploy.
  Values are stored as strings; the service layer casts them using data_type.
- Setting.objects.get_value("key") is the canonical read path so callers
  don't need to know about the type-casting logic.
- A SettingCategory groups related keys for a cleaner admin view.
- Settings marked is_sensitive=True are masked in the admin list display
  and audit logs.
"""

from django.db import models
from core.models import TimeStampedModel


class SettingCategory(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "settings_category"
        ordering = ["order", "name"]

    def __str__(self) -> str:
        return self.name


class PlatformSetting(TimeStampedModel):
    """
    Runtime configuration key/value pairs.
    These override the values in config/settings/*.py at the service level.
    """

    class DataType(models.TextChoices):
        STRING  = "string",  "String"
        INTEGER = "integer", "Integer"
        FLOAT   = "float",   "Float"
        BOOLEAN = "boolean", "Boolean"
        JSON    = "json",    "JSON"

    category = models.ForeignKey(
        SettingCategory,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="settings",
    )
    key = models.CharField(max_length=200, unique=True, db_index=True)
    value = models.TextField()
    data_type = models.CharField(
        max_length=10,
        choices=DataType.choices,
        default=DataType.STRING,
    )
    description = models.TextField(blank=True)
    is_sensitive = models.BooleanField(
        default=False,
        help_text="Mask value in admin displays and audit logs",
    )
    is_editable = models.BooleanField(
        default=True,
        help_text="Read-only settings cannot be changed from the admin UI",
    )

    class Meta:
        db_table = "settings_platform_setting"
        ordering = ["category", "key"]
        indexes = [
            models.Index(fields=["key"], name="idx_setting_key"),
        ]

    def __str__(self) -> str:
        return f"{self.key} = {'***' if self.is_sensitive else self.value}"

    def typed_value(self):
        """Return the value cast to its declared Python type."""
        import json
        casts = {
            self.DataType.INTEGER: int,
            self.DataType.FLOAT:   float,
            self.DataType.BOOLEAN: lambda v: v.lower() in ("true", "1", "yes"),
            self.DataType.JSON:    json.loads,
            self.DataType.STRING:  str,
        }
        return casts.get(self.data_type, str)(self.value)
