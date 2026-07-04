"""
apps/authentication/models.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Extends Django's built-in User with a profile and role system.

Design decisions:
- We keep Django's own User model (no custom AbstractUser) because the spec
  uses Django Admin heavily and swapping the user model mid-project risks
  breaking third-party admin tooling. Profile is a OneToOne extension instead.
- Role is a named group with a description; we piggyback on Django's Group
  so admin permission assignment works out of the box.
- UserProfile records last_activity for session-timeout enforcement and
  stores per-user preferences (theme / dark-mode toggle).
"""

from django.db import models
from django.contrib.auth.models import User
from core.models import TimeStampedModel


class Role(TimeStampedModel):
    """
    Named role that maps 1-to-1 with a Django auth.Group.
    The Group carries the actual permissions; Role adds a human description.
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    group = models.OneToOneField(
        "auth.Group",
        on_delete=models.CASCADE,
        related_name="role",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "auth_role"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"], name="idx_role_name"),
        ]

    def __str__(self) -> str:
        return self.name


class UserProfile(TimeStampedModel):
    """One-to-one extension of Django User. Created by post_save signal."""

    class ThemeChoice(models.TextChoices):
        LIGHT = "light", "Light"
        DARK = "dark", "Dark"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        primary_key=True,
    )
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    theme = models.CharField(
        max_length=10,
        choices=ThemeChoice.choices,
        default=ThemeChoice.LIGHT,
    )
    last_activity = models.DateTimeField(null=True, blank=True, db_index=True)
    is_locked = models.BooleanField(default=False)
    failed_login_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "auth_user_profile"

    def __str__(self) -> str:
        return f"Profile({self.user.username})"
