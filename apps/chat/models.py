"""
apps/chat/models.py
~~~~~~~~~~~~~~~~~~~~
Conversation, Message and MessageChunkCitation.

Design decisions:
- Conversation groups messages belonging to one user session.
  Conversations are reopenable (spec: "Allow reopening previous conversations").
- Message stores both the user question and the assistant reply in separate
  rows rather than alternating role columns, so queries like "all questions
  containing X" are trivial.
- MessageChunkCitation links a Message to the DocumentChunks that were used
  to generate the answer, carrying the similarity score and whether the chunk
  was actually quoted — supporting the "Source documents / Similarity score /
  Retrieved chunks" panel in the chat UI.
- ConversationContext caches the full context blob sent to the LLM for each
  assistant turn; useful for debugging hallucinations and for token auditing.
"""

from django.db import models
from django.contrib.auth.models import User
from core.models import BaseModel
from apps.embedding_service.models import DocumentChunk
from apps.ai_agent.models import AIModel


class Conversation(BaseModel):
    """A named, reopenable chat session."""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="conversations",
        db_index=True,
    )
    title = models.CharField(max_length=500, blank=True)
    knowledge_base = models.ForeignKey(
        "knowledge_base.KnowledgeBase",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="conversations",
    )
    is_pinned = models.BooleanField(default=False)
    message_count = models.PositiveIntegerField(default=0)
    # Denormalised to avoid a COUNT() on every list render
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "chat_conversation"
        ordering = ["-last_message_at", "-created_at"]
        indexes = [
            models.Index(fields=["user", "is_deleted"], name="idx_conv_user"),
            models.Index(fields=["user", "last_message_at"], name="idx_conv_user_date"),
        ]

    def __str__(self) -> str:
        return f"Conv({self.id}): {self.title or 'Untitled'}"


class Message(BaseModel):
    """One turn in a conversation (either user question or assistant answer)."""

    class Role(models.TextChoices):
        USER      = "user",      "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM    = "system",    "System"

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
        db_index=True,
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        db_index=True,
    )
    content = models.TextField()
    # For assistant messages only -------------------------------------------
    model_used = models.ForeignKey(
        AIModel,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="messages",
    )
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    generation_time_ms = models.FloatField(null=True, blank=True)
    # Did the agent decide it couldn't answer from context?
    is_fallback_response = models.BooleanField(default=False)
    # Sequence number within the conversation for ordered display
    sequence = models.PositiveIntegerField()

    class Meta:
        db_table = "chat_message"
        ordering = ["conversation", "sequence"]
        indexes = [
            models.Index(fields=["conversation", "sequence"], name="idx_msg_conv_seq"),
            models.Index(fields=["conversation", "role"], name="idx_msg_conv_role"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "sequence"],
                name="uq_message_sequence",
            )
        ]

    def __str__(self) -> str:
        return f"[{self.role}] Conv({self.conversation_id}) #{self.sequence}"


class MessageChunkCitation(BaseModel):
    """
    Links an assistant Message to the DocumentChunks retrieved and used
    to generate it. This drives the "Sources / Citations" panel in the UI.
    """
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="citations",
        db_index=True,
    )
    chunk = models.ForeignKey(
        DocumentChunk,
        on_delete=models.CASCADE,
        related_name="citations",
    )
    rank = models.PositiveSmallIntegerField()
    similarity_score = models.FloatField()
    rerank_score = models.FloatField(null=True, blank=True)
    # Was this chunk's text actually included in the LLM context window?
    included_in_context = models.BooleanField(default=True)

    class Meta:
        db_table = "chat_message_citation"
        ordering = ["message", "rank"]
        constraints = [
            models.UniqueConstraint(
                fields=["message", "chunk"],
                name="uq_citation_msg_chunk",
            )
        ]

    def __str__(self) -> str:
        return f"Citation(msg={self.message_id}, chunk={self.chunk_id}, rank={self.rank})"


class ConversationContext(BaseModel):
    """
    Stores the full context blob (assembled retrieved chunks) that was sent
    to the LLM for each assistant turn. Kept for debugging and token auditing.
    One row per assistant Message.
    """
    message = models.OneToOneField(
        Message,
        on_delete=models.CASCADE,
        related_name="context_snapshot",
    )
    context_text = models.TextField()
    token_count = models.PositiveIntegerField(default=0)
    chunks_used = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "chat_conversation_context"

    def __str__(self) -> str:
        return f"Context(msg={self.message_id}, tokens={self.token_count})"
