"""
apps/ai_agent/models.py
~~~~~~~~~~~~~~~~~~~~~~~~
AIModel and PromptTemplate - the admin-configurable AI layer.

Design decisions:
- AIModel stores every Ollama model the admin has registered so the active
  LLM / embedding / reasoning model can be changed from Django Admin with
  no code change (spec: "allow changing models from Django Admin without
  changing code").
- PromptTemplate stores Jinja2-style templates so prompt engineering can be
  done from the admin UI. The agent renders the template at runtime.
- AgentConfig is a singleton-style settings model; only one row is "active"
  at a time, controlled by the is_active flag + a DB constraint.
"""

from django.db import models
from core.models import TimeStampedModel, BaseModel


class AIModel(TimeStampedModel):
    """
    Registry of Ollama models available to the platform.
    Populated by the admin; the agent/embedding services read from here.
    """

    class ModelType(models.TextChoices):
        LLM        = "llm",        "Language Model (LLM)"
        EMBEDDING  = "embedding",  "Embedding Model"
        REASONING  = "reasoning",  "Reasoning Model"
        CODE       = "code",       "Code Model"

    name = models.CharField(
        max_length=200,
        unique=True,
        help_text="Ollama model name, e.g. 'qwen3:14b-instruct'",
    )
    display_name = models.CharField(max_length=200)
    model_type = models.CharField(
        max_length=20,
        choices=ModelType.choices,
        db_index=True,
    )
    ollama_url = models.URLField(
        default="http://127.0.0.1:11434",
        help_text="Ollama API base URL for this model",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    is_default = models.BooleanField(
        default=False,
        help_text="One default per model_type; enforced via admin clean()",
    )
    context_window = models.PositiveIntegerField(
        default=4096,
        help_text="Maximum context tokens supported by this model",
    )
    vector_dimensions = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Output dimensions (embedding models only)",
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "ai_model"
        ordering = ["model_type", "name"]
        indexes = [
            models.Index(fields=["model_type", "is_default"], name="idx_aimodel_type_default"),
        ]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.get_model_type_display()})"


class PromptTemplate(TimeStampedModel):
    """
    Admin-editable prompt templates.
    The agent renders these with Python .format_map() using the keys
    {context}, {question}, {history}.
    """

    class TemplateType(models.TextChoices):
        RAG          = "rag",          "RAG Answer"
        SYSTEM       = "system",       "System Prompt"
        SUMMARISE    = "summarise",    "Document Summarisation"
        RERANK       = "rerank",       "Re-ranking"
        FALLBACK     = "fallback",     "No-Context Fallback"

    name = models.CharField(max_length=200, unique=True)
    template_type = models.CharField(
        max_length=20,
        choices=TemplateType.choices,
        db_index=True,
    )
    template_text = models.TextField(
        help_text="Use {context}, {question}, {history} as placeholders",
    )
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    version = models.PositiveSmallIntegerField(default=1)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "ai_prompt_template"
        ordering = ["template_type", "name"]

    def __str__(self) -> str:
        return f"{self.name} (v{self.version})"


class AgentConfig(TimeStampedModel):
    """
    Singleton configuration for the AI agent.
    Only one row should have is_active=True at any time.
    """
    name = models.CharField(max_length=200, default="Default Config")
    is_active = models.BooleanField(default=True, db_index=True)

    # Model selection (FK to AIModel rows)
    llm_model = models.ForeignKey(
        AIModel,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_configs_llm",
        limit_choices_to={"model_type": "llm"},
    )
    embedding_model = models.ForeignKey(
        AIModel,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_configs_emb",
        limit_choices_to={"model_type": "embedding"},
    )

    # RAG retrieval settings
    top_k = models.PositiveSmallIntegerField(default=5)
    similarity_threshold = models.FloatField(default=0.0)
    max_context_tokens = models.PositiveIntegerField(default=3000)
    enable_reranking = models.BooleanField(default=False)

    # LLM generation settings (spec: Temperature / Top P / Top K / Max Tokens)
    temperature = models.FloatField(default=0.1)
    top_p = models.FloatField(default=0.9)
    top_k_llm = models.PositiveSmallIntegerField(default=40)
    max_tokens = models.PositiveSmallIntegerField(default=1024)

    # Prompt templates
    rag_prompt = models.ForeignKey(
        PromptTemplate,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_configs_rag",
        limit_choices_to={"template_type": "rag"},
    )

    class Meta:
        db_table = "ai_agent_config"

    def __str__(self) -> str:
        return f"AgentConfig: {self.name} [active={self.is_active}]"
