"""
Management command: python manage.py index_documents

Re-indexes documents that are stuck in CHUNKING status or failed.
Safe to run multiple times (incremental indexing skips already-embedded chunks).

Usage:
  python manage.py index_documents                 # all CHUNKING documents
  python manage.py index_documents --doc-id 42     # specific document
  python manage.py index_documents --force         # re-embed even if already done
  python manage.py index_documents --limit 10      # process at most 10 docs
"""

import logging
from django.core.management.base import BaseCommand, CommandError
from apps.document_upload.models import Document
from core.embeddings.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Index (chunk + embed) documents that are in CHUNKING status."

    def add_arguments(self, parser):
        parser.add_argument(
            "--doc-id", type=int, default=None,
            help="Process a specific document by PK.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Re-embed chunks even if already embedded.",
        )
        parser.add_argument(
            "--limit", type=int, default=100,
            help="Maximum number of documents to process (default: 100).",
        )
        parser.add_argument(
            "--status", default="chunking",
            help="Process documents with this status (default: chunking).",
        )

    def handle(self, *args, **options):
        service = EmbeddingService()

        if options["doc_id"]:
            try:
                doc = Document.objects.get(pk=options["doc_id"], is_deleted=False)
            except Document.DoesNotExist:
                raise CommandError(f"Document #{options['doc_id']} not found.")
            self.stdout.write(f"Indexing document #{doc.pk}: {doc.title}")
            summary = service.index_document(doc, force=options["force"])
            self._print_summary(doc, summary)
            return

        status = options["status"]
        docs = Document.objects.filter(
            status=status, is_deleted=False
        ).order_by("created_at")[: options["limit"]]

        count = docs.count()
        if count == 0:
            self.stdout.write(self.style.WARNING(
                f"No documents with status='{status}' found."
            ))
            return

        self.stdout.write(f"Found {count} document(s) to index...")
        total_chunks = 0
        errors = 0

        for doc in docs:
            self.stdout.write(f"  → #{doc.pk} {doc.title[:60]}")
            summary = service.index_document(doc, force=options["force"])
            self._print_summary(doc, summary)
            total_chunks += summary.get("chunks_embedded", 0)
            if summary.get("error"):
                errors += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {count - errors}/{count} documents indexed, "
            f"{total_chunks} total chunks embedded, {errors} error(s)."
        ))

    def _print_summary(self, doc, summary):
        if summary.get("error"):
            self.stdout.write(self.style.ERROR(
                f"     ✗ Error: {summary['error']}"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"     ✓ {summary['chunks_created']} chunks, "
                f"{summary['chunks_embedded']} embedded in {summary['elapsed_s']}s"
            ))
