"""
core/models.py
~~~~~~~~~~~~~~
Abstract base classes shared across every Django app.

Design decisions:
- AuditMixin: adds created_at, modified_at, created_by, modified_by to every
  concrete model so we have full provenance without repeating fields.
- SoftDeleteMixin: sets is_deleted + deleted_at instead of issuing DELETE SQL,
  preserving referential integrity and the audit trail. Pair with SoftDeleteManager
  so normal querysets automatically exclude deleted rows.
- TimeStampedModel: AuditMixin only (no soft-delete) for lightweight join/config tables.
- BaseModel: AuditMixin + SoftDeleteMixin - the standard base for most domain models.
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone


# ---------------------------------------------------------------------------
# Managers
# ---------------------------------------------------------------------------

class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(is_deleted=False)

    def deleted(self):
        return self.filter(is_deleted=True)

    def delete(self):
        """Soft-delete all rows in the queryset."""
        return self.update(is_deleted=True, deleted_at=timezone.now())

    def hard_delete(self):
        """Permanently remove rows (admin / data-purge use only)."""
        return super().delete()


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()

    def all_with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db)

    def deleted_only(self):
        return SoftDeleteQuerySet(self.model, using=self._db).deleted()


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------

class AuditMixin(models.Model):
    """
    Adds four audit columns to every model that inherits it.
    created_by / modified_by are nullable so system-generated rows
    (migrations, management commands) don't require a real user.
    """
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_created",
        db_index=True,
    )
    modified_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_modified",
    )

    class Meta:
        abstract = True


class SoftDeleteMixin(models.Model):
    """
    Soft-delete support. Overrides the default manager so .objects.all()
    excludes deleted rows automatically.
    """
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()

    def delete(self, using=None, keep_parents=False):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])

    def hard_delete(self):
        super().delete()

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at"])

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Concrete abstract bases (combine the mixins)
# ---------------------------------------------------------------------------

class TimeStampedModel(AuditMixin):
    """Audit fields only — suitable for config/lookup tables."""
    class Meta:
        abstract = True


class BaseModel(AuditMixin, SoftDeleteMixin):
    """
    Full-featured base: audit fields + soft delete.
    The standard parent for all domain models in this project.
    """
    class Meta:
        abstract = True
