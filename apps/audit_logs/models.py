"""
apps/audit_logs/models.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
AuditLog - immutable event log for all user and system actions.

Design decisions:
- AuditLog rows are NEVER soft-deleted; they are the audit trail.
  No BaseModel inheritance here — we use plain Model with explicit
  created_at only (no modified_at / deleted fields).
- action_type uses a broad enum so logs can be filtered by category
  (uploads, searches, LLM calls, auth events, admin changes, errors).
- The before_state / after_state JSON columns let admins see exactly
  what changed on any model (populated by the audit middleware in Phase 8).
- ip_address and user_agent support security investigations.
"""

from django.db import models
from django.contrib.auth.models import User


class AuditLog(models.Model):
    """
    Immutable event record. No soft-delete, no update fields.
    Written once and never changed.
    """

    class ActionType(models.TextChoices):
        # Auth
        LOGIN          = "login",          "User Login"
        LOGOUT         = "logout",         "User Logout"
        LOGIN_FAILED   = "login_failed",   "Login Failed"
        PASSWORD_RESET = "password_reset", "Password Reset"
        # Document pipeline
        UPLOAD         = "upload",         "Document Uploaded"
        OCR_START      = "ocr_start",      "OCR Started"
        OCR_COMPLETE   = "ocr_complete",   "OCR Completed"
        OCR_FAILED     = "ocr_failed",     "OCR Failed"
        INDEX_START    = "index_start",    "Indexing Started"
        INDEX_COMPLETE = "index_complete", "Indexing Completed"
        INDEX_FAILED   = "index_failed",   "Indexing Failed"
        DELETE_DOC     = "delete_doc",     "Document Deleted"
        # Search / RAG
        SEARCH         = "search",         "Vector Search"
        LLM_CALL       = "llm_call",       "LLM API Call"
        # Conversation
        CHAT_START     = "chat_start",     "Conversation Started"
        CHAT_MESSAGE   = "chat_message",   "Chat Message Sent"
        # Admin / config
        SETTINGS_CHANGE = "settings_change", "Settings Changed"
        USER_CREATE    = "user_create",    "User Created"
        USER_UPDATE    = "user_update",    "User Updated"
        USER_DELETE    = "user_delete",    "User Deleted"
        ROLE_CHANGE    = "role_change",    "Role / Permission Changed"
        # Errors
        ERROR          = "error",          "Application Error"

    # Who/when
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # What
    action_type = models.CharField(
        max_length=30,
        choices=ActionType.choices,
        db_index=True,
    )
    description = models.TextField(blank=True)

    # Target object (generic so any model can be referenced)
    content_type = models.ForeignKey(
        "contenttypes.ContentType",
        null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    object_id = models.CharField(max_length=50, blank=True, db_index=True)
    object_repr = models.CharField(max_length=500, blank=True)

    # State snapshots
    before_state = models.JSONField(null=True, blank=True)
    after_state = models.JSONField(null=True, blank=True)

    # Request context
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.CharField(max_length=500, blank=True)
    request_path = models.CharField(max_length=500, blank=True)

    # Performance data (for LLM_CALL / SEARCH events)
    duration_ms = models.FloatField(null=True, blank=True)
    extra_data = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"], name="idx_audit_user_date"),
            models.Index(fields=["action_type", "created_at"], name="idx_audit_type_date"),
            models.Index(fields=["ip_address"], name="idx_audit_ip"),
        ]

    def __str__(self) -> str:
        username = self.user.username if self.user_id else "system"
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {username}: {self.action_type}"
