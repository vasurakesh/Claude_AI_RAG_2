"""
apps/vector_search/models.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SearchQuery and SearchResult - logged for analytics and re-ranking training.

Design decisions:
- Every RAG search is logged so admins can see what users are asking and
  tune retrieval quality (Top-K, similarity threshold, re-ranker settings).
- SearchResult rows capture the exact chunks returned and their scores,
  enabling offline evaluation of retrieval quality.
"""

from django.db import models
from django.contrib.auth.models import User
from core.models import BaseModel
from apps.embedding_service.models import DocumentChunk


class SearchQuery(BaseModel):
    """One vector similarity search triggered by a user question."""

    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="search_queries",
        db_index=True,
    )
    query_text = models.TextField()
    query_embedding_model = models.CharField(max_length=200)
    top_k = models.PositiveSmallIntegerField(default=5)
    similarity_threshold = models.FloatField(default=0.0)

    # Performance telemetry
    embedding_time_ms = models.FloatField(null=True, blank=True)
    search_time_ms = models.FloatField(null=True, blank=True)
    total_results = models.PositiveSmallIntegerField(default=0)

    # Which knowledge base was searched (null = global search)
    knowledge_base = models.ForeignKey(
        "knowledge_base.KnowledgeBase",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="search_queries",
    )

    class Meta:
        db_table = "search_query"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"], name="idx_search_user_date"),
        ]

    def __str__(self) -> str:
        return f"Search({self.id}): {self.query_text[:60]}"


class SearchResult(BaseModel):
    """One chunk returned by a SearchQuery, with its similarity score."""
    query = models.ForeignKey(
        SearchQuery,
        on_delete=models.CASCADE,
        related_name="results",
    )
    chunk = models.ForeignKey(
        DocumentChunk,
        on_delete=models.CASCADE,
        related_name="search_results",
    )
    rank = models.PositiveSmallIntegerField()
    similarity_score = models.FloatField()
    # Score after optional re-ranking (null if re-ranker not applied)
    rerank_score = models.FloatField(null=True, blank=True)
    # Was this result ultimately included in the LLM context?
    used_in_context = models.BooleanField(default=True)

    class Meta:
        db_table = "search_result"
        ordering = ["query", "rank"]
        constraints = [
            models.UniqueConstraint(
                fields=["query", "rank"],
                name="uq_search_result_rank",
            )
        ]

    def __str__(self) -> str:
        return f"Result({self.query_id}, rank={self.rank}, score={self.similarity_score:.3f})"
