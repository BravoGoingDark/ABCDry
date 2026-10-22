"""Build (or refresh) the retrieval index used by the AgroAI assistant."""
import time

from django.core.management.base import BaseCommand

from dashboard.services import retrieval


class Command(BaseCommand):
    help = "Chunk docs/*.md and the crop knowledge base, then build the hybrid retrieval index."

    def add_arguments(self, parser):
        parser.add_argument('--lexical', action='store_true',
                            help='Skip the embedding call and build the TF-IDF index only.')
        parser.add_argument('--query', default='',
                            help='Print the ranked retrieval for this question and exit.')
        parser.add_argument('--top-k', type=int, default=5)

    def handle(self, *args, **options):
        cfg = retrieval.rag_config()
        self.stdout.write(f'  RAG enabled     : {cfg["enabled"]}')
        self.stdout.write(f'  docs directory  : {retrieval._docs_dir()}')
        self.stdout.write(f'  index directory : {retrieval._index_dir()}')

        if options['query']:
            context = retrieval.gather(options['query'])
            self.stdout.write(f'  chunks indexed  : {context["chunks"]} '
                              f'(dense={context["dense"]}, sig={context["signature"][:10]})')
            for position, hit in enumerate(context['documents'], 1):
                self.stdout.write(f'  {position}. {hit["source"]} '
                                  f'(fused {hit["score"]}, rel {hit["relevance"]})')
            for line in context['data']:
                self.stdout.write(f'  DATA: {line}')
            return

        started = time.time()
        installed = retrieval.embedding_model_installed()
        embed = not options['lexical'] and installed
        if not options['lexical'] and not installed:
            self.stdout.write(self.style.WARNING(
                f'  embedding model "{cfg["model"]}" is not installed - building the '
                f'lexical index only (run: ollama pull {cfg["model"]})'))

        index = retrieval.build_index(embed=embed)
        retrieval.reset_index_cache()
        vectors = 'yes' if index.vectors is not None else 'no'
        self.stdout.write(self.style.SUCCESS(
            f'  built {len(index.chunks)} chunks, dense vectors: {vectors} '
            f'in {time.time() - started:.1f}s'))
        self.stdout.write(f'  signature       : {index.signature[:16]}')
