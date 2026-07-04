"""
apps/knowledge_base/models.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
KnowledgeBase and Tag - the top-level organisational containers.
Documents are filed inside a KnowledgeBase so multi-tenant / project
separation is possible without multiple Django installations.
"""

from django.db import models
from core.models import BaseModel


class KnowledgeBase(BaseModel):
    """
    Top-level container. One project / department per KB.
    Multiple users can have access; permissions are managed via Django Groups.
    """
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, db_index=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    # Allow restricting KB access to specific groups (empty = unrestricted)
    allowed_groups = models.ManyToManyField(
        "auth.Group",
        blank=True,
        related_name="knowledge_bases",
    )

    class Meta:
        db_table = "kb_knowledge_base"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["slug"], name="idx_kb_slug"),
            models.Index(fields=["is_active", "is_deleted"], name="idx_kb_active"),
        ]

    def __str__(self) -> str:
        return self.name


class Tag(BaseModel):
    """Flat tag taxonomy. Documents can carry multiple tags."""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    color = models.CharField(max_length=7, default="#6c757d")  # hex colour for UI badge

    class Meta:
        db_table = "kb_tag"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
