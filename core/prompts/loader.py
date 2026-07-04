"""
core/prompts/loader.py
~~~~~~~~~~~~~~~~~~~~~~~~
PromptTemplateLoader — resolves the active template for a given type.

Priority order:
  1. Active default row in PromptTemplate table (admin-editable from Django Admin)
  2. Fallback to the Python constants in core/prompts/templates.py

This means the admin can iterate on prompts without a code deploy,
while the constants serve as a safe fallback if the DB has no row yet.
"""
import logging
from typing import Optional
from . import templates as T

logger = logging.getLogger(__name__)

_TYPE_FALLBACK = {
    "rag":       T.RAG_ANSWER,
    "system":    T.SYSTEM_PROMPT,
    "fallback":  T.FALLBACK_NO_CONTEXT,
    "rerank":    T.RERANK_PROMPT,
    "summarise": T.SUMMARISE_PROMPT,
}


def load(template_type: str) -> str:
    """
    Return the active template text for the given template_type.
    Falls back to the Python constant if no DB row found.
    """
    try:
        from apps.ai_agent.models import PromptTemplate
        row = PromptTemplate.objects.filter(
            template_type=template_type,
            is_active=True,
            is_default=True,
        ).order_by("-version").first()
        if row:
            return row.template_text
    except Exception as e:
        logger.debug("PromptTemplate DB lookup failed: %s", e)

    return _TYPE_FALLBACK.get(template_type, T.RAG_ANSWER)


def render(template_type: str, **kwargs) -> str:
    """Load template and substitute kwargs using str.format_map()."""
    tmpl = load(template_type)
    try:
        return tmpl.format_map(kwargs)
    except KeyError as e:
        logger.warning("Prompt template missing placeholder: %s", e)
        return tmpl
