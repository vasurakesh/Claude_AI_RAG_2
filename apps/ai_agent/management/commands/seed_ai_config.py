"""
python manage.py seed_ai_config

Creates the default AIModel rows, PromptTemplate rows, and AgentConfig
in the database so the RAG pipeline works out-of-the-box without
requiring manual Django Admin configuration.

Safe to run multiple times (uses get_or_create).
"""
from django.core.management.base import BaseCommand
from apps.ai_agent.models import AIModel, PromptTemplate, AgentConfig
from core.prompts.templates import (
    RAG_ANSWER, SYSTEM_PROMPT, FALLBACK_NO_CONTEXT,
    RERANK_PROMPT, SUMMARISE_PROMPT, CONTEXT_RELEVANCE_CHECK,
)


MODELS = [
    dict(name="nomic-embed-text",      display_name="Nomic Embed Text",
         model_type=AIModel.ModelType.EMBEDDING, is_default=True,
         vector_dimensions=768, context_window=8192),
    dict(name="qwen3:14b-instruct",    display_name="Qwen3 14B Instruct",
         model_type=AIModel.ModelType.LLM,       is_default=True,
         context_window=32768),
    dict(name="llama3.1:8b-instruct",  display_name="Llama 3.1 8B Instruct",
         model_type=AIModel.ModelType.LLM,       is_default=False,
         context_window=131072),
    dict(name="deepseek-r1:latest",    display_name="DeepSeek R1",
         model_type=AIModel.ModelType.REASONING, is_default=True,
         context_window=65536),
    dict(name="qwen2.5-coder:latest",  display_name="Qwen2.5 Coder",
         model_type=AIModel.ModelType.CODE,      is_default=True,
         context_window=131072),
]

TEMPLATES = [
    dict(name="Default RAG Answer",      template_type="rag",      template_text=RAG_ANSWER,              is_default=True),
    dict(name="Default System Prompt",   template_type="system",   template_text=SYSTEM_PROMPT,           is_default=True),
    dict(name="Default Fallback",        template_type="fallback", template_text=FALLBACK_NO_CONTEXT,     is_default=True),
    dict(name="Default Re-rank",         template_type="rerank",   template_text=RERANK_PROMPT,           is_default=True),
    dict(name="Default Summarise",       template_type="summarise",template_text=SUMMARISE_PROMPT,        is_default=True),
]


class Command(BaseCommand):
    help = "Seed default AI models, prompt templates, and agent config."

    def handle(self, *args, **options):
        # --- AI Models ---
        self.stdout.write("Seeding AI models...")
        for m in MODELS:
            obj, created = AIModel.objects.get_or_create(
                name=m["name"],
                defaults={k: v for k, v in m.items() if k != "name"},
            )
            self.stdout.write(
                f"  {'Created' if created else 'Exists '}: {obj.display_name}"
            )

        # --- Prompt templates ---
        self.stdout.write("Seeding prompt templates...")
        for t in TEMPLATES:
            obj, created = PromptTemplate.objects.get_or_create(
                name=t["name"],
                defaults={k: v for k, v in t.items() if k != "name"},
            )
            self.stdout.write(
                f"  {'Created' if created else 'Exists '}: {obj.name}"
            )

        # --- Agent config ---
        self.stdout.write("Seeding agent config...")
        llm = AIModel.objects.filter(
            model_type=AIModel.ModelType.LLM, is_default=True
        ).first()
        emb = AIModel.objects.filter(
            model_type=AIModel.ModelType.EMBEDDING, is_default=True
        ).first()
        rag_tmpl = PromptTemplate.objects.filter(
            template_type="rag", is_default=True
        ).first()

        cfg, created = AgentConfig.objects.get_or_create(
            name="Default Config",
            defaults=dict(
                is_active=True,
                llm_model=llm,
                embedding_model=emb,
                rag_prompt=rag_tmpl,
                top_k=5,
                similarity_threshold=0.0,
                max_context_tokens=3000,
                enable_reranking=False,
                temperature=0.1,
                top_p=0.9,
                top_k_llm=40,
                max_tokens=1024,
            ),
        )
        self.stdout.write(
            f"  {'Created' if created else 'Exists '}: {cfg.name}"
        )
        self.stdout.write(self.style.SUCCESS("\nAI configuration seeded successfully."))
        self.stdout.write(
            "\nNext steps:\n"
            "  1. Start Ollama:               ollama serve\n"
            "  2. Pull embedding model:       ollama pull nomic-embed-text\n"
            "  3. Pull LLM:                   ollama pull qwen3:14b-instruct\n"
            "  4. Upload documents and index them\n"
            "  5. Open http://127.0.0.1:8000/chat/ and start asking questions\n"
        )
