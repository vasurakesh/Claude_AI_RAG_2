"""
python manage.py reindex_document <pk> [--force]
Force re-chunk and re-embed a single document, clearing its existing vectors.
"""
from django.core.management.base import BaseCommand, CommandError
from apps.document_upload.models import Document
from core.embeddings.embedding_service import EmbeddingService


class Command(BaseCommand):
    help = "Force re-index a single document (clears existing chunks/vectors)."

    def add_arguments(self, parser):
        parser.add_argument("pk", type=int, help="Document primary key")
        parser.add_argument("--force", action="store_true",
                            help="Re-embed even if chunks are already embedded.")

    def handle(self, *args, **options):
        try:
            doc = Document.objects.get(pk=options["pk"], is_deleted=False)
        except Document.DoesNotExist:
            raise CommandError(f"Document #{options['pk']} not found.")

        service = EmbeddingService()
        self.stdout.write(f"Clearing existing vectors for #{doc.pk}...")
        service.delete_document_vectors(doc)

        # Reset status so the pipeline re-runs chunking
        doc.status = Document.Status.CHUNKING
        doc.save(update_fields=["status"])

        self.stdout.write(f"Re-indexing #{doc.pk}: {doc.title}")
        summary = service.index_document(doc, force=options["force"])

        if summary.get("error"):
            self.stdout.write(self.style.ERROR(f"Failed: {summary['error']}"))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Done: {summary['chunks_created']} chunks, "
                f"{summary['chunks_embedded']} embedded in {summary['elapsed_s']}s"
            ))
