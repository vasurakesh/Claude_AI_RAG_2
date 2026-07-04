"""
core/agents/rag_agent.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
RAGAgent — the top-level orchestrator for the full RAG pipeline.

Responsibilities (spec: AI Agent Layer):
  ✓ Planning         — decides retrieve-then-generate vs fallback
  ✓ Retrieval        — delegates to RetrievalService
  ✓ Context validation — delegates to ContextBuilder.check_relevance
  ✓ Prompt generation — uses PromptTemplateLoader
  ✓ Hallucination reduction — relevance gate + citation-anchored prompts
  ✓ Citation generation — every answer includes structured source references
  ✓ Memory           — injects last N conversation turns into the prompt
  ✓ Token optimisation — context trimmed to budget by ContextBuilder

Public API:
  answer = agent.ask(question, conversation_id, user, knowledge_base_id)
  answer.text          → the generated text
  answer.sources       → list[ContextSource] for the UI citations panel
  answer.model_used    → model name string
  answer.generation_time_ms
  answer.prompt_tokens / completion_tokens
  answer.is_fallback   → True when context was empty / irrelevant
  answer.search_query_id → FK to SearchQuery for the audit trail
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from django.contrib.auth.models import User
from django.utils import timezone

from apps.chat.models import (
    Conversation, Message, MessageChunkCitation, ConversationContext,
)
from core.ai.ollama_client import OllamaClient, OllamaError
from core.prompts import loader as prompt_loader
from .context_builder import BuiltContext, ContextBuilder, ContextSource
from .retriever import RetrievalService, RetrievalResult

logger = logging.getLogger(__name__)

# Number of previous conversation turns injected into the prompt
HISTORY_TURNS = 6


@dataclass
class AgentAnswer:
    text: str
    sources: list[ContextSource] = field(default_factory=list)
    model_used: str = ""
    generation_time_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    is_fallback: bool = False
    search_query_id: Optional[int] = None
    context_token_count: int = 0
    chunks_used: int = 0


class RAGAgent:

    def __init__(
        self,
        ollama_client: Optional[OllamaClient] = None,
        retrieval_service: Optional[RetrievalService] = None,
        context_builder: Optional[ContextBuilder] = None,
    ):
        self._ollama   = ollama_client    or OllamaClient()
        self._retriever = retrieval_service or RetrievalService(self._ollama)
        self._builder  = context_builder  or ContextBuilder()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ask(
        self,
        question: str,
        conversation: Optional[Conversation] = None,
        user: Optional[User] = None,
        knowledge_base_id: Optional[int] = None,
    ) -> AgentAnswer:
        """
        Full RAG pipeline for one user question.
        Persists Message + Citation + ConversationContext rows.
        """
        cfg = self._get_agent_config()
        llm_model = self._get_llm_model(cfg)

        logger.info(
            "RAGAgent.ask: '%s' | kb=%s | conv=%s | model=%s",
            question[:80], knowledge_base_id,
            conversation.pk if conversation else None, llm_model,
        )

        # --- Step 1: Persist user message ------------------------------
        user_msg = self._save_message(
            conversation=conversation,
            role=Message.Role.USER,
            content=question,
        )

        # --- Step 2: Retrieve ------------------------------------------
        try:
            retrieval: RetrievalResult = self._retriever.retrieve(
                query=question,
                knowledge_base_id=knowledge_base_id,
                user=user,
            )
        except OllamaError as e:
            answer = self._fallback(
                question,
                reason=f"Embedding service unavailable: {e}",
                conversation=conversation,
            )
            self._save_message(
                conversation=conversation,
                role=Message.Role.ASSISTANT,
                content=answer.text,
                is_fallback=True,
                model_name=llm_model,
            )
            return answer

        # --- Step 3: Build context -------------------------------------
        validate = cfg.enable_reranking if cfg else False
        built: BuiltContext = self._builder.build(
            retrieved_chunks=retrieval.chunks,
            validate_relevance=validate,
            question=question,
            ollama_client=self._ollama,
        )

        # --- Step 4: Fallback if no usable context --------------------
        if not built.is_relevant or not built.context_text:
            fallback_text = prompt_loader.render("fallback", question=question)
            answer = AgentAnswer(
                text=fallback_text,
                is_fallback=True,
                model_used=llm_model,
                search_query_id=retrieval.search_query_id,
            )
            self._save_message(
                conversation=conversation,
                role=Message.Role.ASSISTANT,
                content=fallback_text,
                is_fallback=True,
                model_name=llm_model,
            )
            return answer

        # --- Step 5: Build prompt + generate --------------------------
        history = self._build_history(conversation)
        prompt  = prompt_loader.render(
            "rag",
            context=built.context_text,
            history=history,
            question=question,
        )
        system = prompt_loader.load("system")

        t0 = time.perf_counter()
        try:
            llm_params = self._get_llm_params(cfg)
            resp = self._ollama.generate(
                prompt=prompt,
                system=system,
                model=llm_model,
                **llm_params,
            )
        except OllamaError as e:
            answer = self._fallback(
                question,
                reason=f"LLM unavailable: {e}",
                conversation=conversation,
            )
            return answer
        gen_ms = (time.perf_counter() - t0) * 1000

        answer_text      = (resp.get("response") or "").strip()
        prompt_tokens    = resp.get("prompt_eval_count") or 0
        completion_tokens = resp.get("eval_count") or 0

        # --- Step 6: Persist assistant message + citations ------------
        assistant_msg = self._save_message(
            conversation=conversation,
            role=Message.Role.ASSISTANT,
            content=answer_text,
            model_name=llm_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            generation_time_ms=gen_ms,
            is_fallback=False,
        )

        if assistant_msg:
            self._save_citations(assistant_msg, retrieval.chunks)
            self._save_context_snapshot(assistant_msg, built)

        # --- Step 7: Update conversation metadata ---------------------
        if conversation:
            conversation.last_message_at = timezone.now()
            conversation.message_count   = (
                Message.objects.filter(conversation=conversation).count()
            )
            if not conversation.title:
                conversation.title = question[:120]
            conversation.save(update_fields=[
                "last_message_at", "message_count", "title"
            ])

        logger.info(
            "Answer generated: %d chars | %d chunks | %.0fms | %d+%d tokens",
            len(answer_text), built.chunks_used, gen_ms,
            prompt_tokens, completion_tokens,
        )

        return AgentAnswer(
            text=answer_text,
            sources=built.sources,
            model_used=llm_model,
            generation_time_ms=gen_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            is_fallback=False,
            search_query_id=retrieval.search_query_id,
            context_token_count=built.token_count,
            chunks_used=built.chunks_used,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_agent_config(self):
        try:
            from apps.ai_agent.models import AgentConfig
            return AgentConfig.objects.select_related(
                "llm_model", "embedding_model", "rag_prompt"
            ).filter(is_active=True).first()
        except Exception:
            return None

    def _get_llm_model(self, cfg=None) -> str:
        if cfg and cfg.llm_model:
            return cfg.llm_model.name
        from django.conf import settings
        return getattr(settings, "DEFAULT_LLM_MODEL", "qwen3:14b-instruct")

    def _get_llm_params(self, cfg=None) -> dict:
        if cfg:
            return {
                "temperature": cfg.temperature,
                "top_p":       cfg.top_p,
                "top_k":       cfg.top_k_llm,
                "max_tokens":  cfg.max_tokens,
            }
        return {"temperature": 0.1, "top_p": 0.9, "top_k": 40, "max_tokens": 1024}

    def _build_history(self, conversation: Optional[Conversation]) -> str:
        if not conversation:
            return ""
        recent = Message.objects.filter(
            conversation=conversation,
            role__in=[Message.Role.USER, Message.Role.ASSISTANT],
            is_deleted=False,
        ).order_by("-sequence")[:HISTORY_TURNS * 2]

        turns = []
        for msg in reversed(list(recent)):
            prefix = "User" if msg.role == Message.Role.USER else "Assistant"
            turns.append(f"{prefix}: {msg.content[:500]}")
        return "\n".join(turns) if turns else "No prior conversation."

    def _save_message(
        self,
        conversation: Optional[Conversation],
        role: str,
        content: str,
        model_name: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        generation_time_ms: float = 0.0,
        is_fallback: bool = False,
    ) -> Optional[Message]:
        if not conversation:
            return None
        try:
            seq = (
                Message.objects.filter(conversation=conversation)
                .order_by("-sequence")
                .values_list("sequence", flat=True)
                .first() or 0
            ) + 1

            model_obj = None
            if model_name:
                try:
                    from apps.ai_agent.models import AIModel
                    model_obj = AIModel.objects.filter(name=model_name).first()
                except Exception:
                    pass

            return Message.objects.create(
                conversation=conversation,
                role=role,
                content=content,
                sequence=seq,
                model_used=model_obj,
                prompt_tokens=prompt_tokens or None,
                completion_tokens=completion_tokens or None,
                generation_time_ms=generation_time_ms or None,
                is_fallback_response=is_fallback,
            )
        except Exception as e:
            logger.error("Failed to save message: %s", e)
            return None

    def _save_citations(self, message: Message, chunks) -> None:
        try:
            citations = [
                MessageChunkCitation(
                    message=message,
                    chunk=rc.chunk,
                    rank=rc.rank,
                    similarity_score=rc.similarity_score,
                    rerank_score=rc.rerank_score,
                    included_in_context=True,
                )
                for rc in chunks
            ]
            MessageChunkCitation.objects.bulk_create(citations, ignore_conflicts=True)
        except Exception as e:
            logger.warning("Failed to save citations: %s", e)

    def _save_context_snapshot(
        self, message: Message, built: BuiltContext
    ) -> None:
        try:
            ConversationContext.objects.create(
                message=message,
                context_text=built.context_text[:50000],
                token_count=built.token_count,
                chunks_used=built.chunks_used,
            )
        except Exception as e:
            logger.warning("Failed to save context snapshot: %s", e)

    def _fallback(
        self,
        question: str,
        reason: str = "",
        conversation: Optional[Conversation] = None,
    ) -> AgentAnswer:
        text = prompt_loader.render("fallback", question=question)
        if reason:
            text += f"\n\n_Technical note: {reason}_"
        return AgentAnswer(text=text, is_fallback=True)


# Module-level singleton
rag_agent = RAGAgent()
