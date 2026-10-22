"""Retrieval-augmented context for the AgroAI farmer assistant.

Two retrieval channels feed the LLM prompt:

* documents - the project knowledge base (``docs/*.md``) plus the structured
  crop knowledge in :mod:`dashboard.services.crop_kb`, chunked, embedded and
  searched with a hybrid of dense vectors (local Ollama embeddings) and
  TF-IDF cosine similarity fused with reciprocal rank fusion.
* data - short factual digests computed live from the project tables for the
  resolved region (recent extremes, satellite status, drought index trend).

Everything degrades gracefully: no embedding model, a missing index or a
database hiccup only reduces the retrieved context, it never breaks an answer.
"""
import hashlib
import json
import logging
import os
import re
import threading
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

CHUNK_CHARS = 1100
CHUNK_OVERLAP = 200
MIN_CHUNK_CHARS = 120
RRF_K = 60
INDEX_VERSION = 'rag-1'
_MONTHS_EN = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
              'August', 'September', 'October', 'November', 'December']


def rag_config():
    """Retrieval settings, read from Django settings / environment."""
    return {
        'enabled': bool(getattr(settings, 'RAG_ENABLED', True)),
        'url': getattr(settings, 'RAG_OLLAMA_URL',
                       getattr(settings, 'ASSISTANT_LLM_URL', 'http://localhost:11434')),
        'model': getattr(settings, 'RAG_EMBED_MODEL', 'bge-m3'),
        'embed_timeout': int(getattr(settings, 'RAG_EMBED_TIMEOUT', 300)),
        'top_k': int(getattr(settings, 'RAG_TOP_K', 4)),
        'lexical_depth': int(getattr(settings, 'RAG_LEXICAL_DEPTH', 12)),
        'max_chars': int(getattr(settings, 'RAG_MAX_CONTEXT_CHARS', 2600)),
        'max_per_source': int(getattr(settings, 'RAG_MAX_PER_SOURCE', 2)),
        'min_score': float(getattr(settings, 'RAG_MIN_SCORE', 0.01)),
        'auto_embed': bool(getattr(settings, 'RAG_AUTO_EMBED', True)),
        'data_window_days': int(getattr(settings, 'RAG_DATA_WINDOW_DAYS', 400)),
    }


# --------------------------------------------------------------------------- #
# Corpus
# --------------------------------------------------------------------------- #
def _docs_dir():
    override = getattr(settings, 'RAG_DOCS_DIR', '') or ''
    if override:
        return Path(override)
    return Path(getattr(settings, 'BASE_DIR', Path.cwd())) / 'docs'


def _index_dir():
    override = getattr(settings, 'RAG_INDEX_DIR', '') or ''
    if override:
        return Path(override)
    return Path(getattr(settings, 'BASE_DIR', Path.cwd())) / 'assistant_index'


def _split_long(text, size=CHUNK_CHARS, overlap=CHUNK_OVERLAP):
    """Window `text` into overlapping blocks on sentence-ish boundaries."""
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if len(text) <= size:
        return [text] if text else []
    blocks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind('. '), window.rfind('\n'), window.rfind('; '))
            if cut > size * 0.6:
                end = start + cut + 1
        blocks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [b for b in blocks if b]


def _markdown_chunks(path):
    """Split a markdown file into heading-scoped chunks."""
    try:
        raw = path.read_text(encoding='utf-8', errors='ignore')
    except OSError as exc:
        logger.warning('rag: cannot read %s (%s)', path, exc)
        return []
    title = path.stem.replace('_', ' ').title()
    chunks = []
    section = title
    buffer = []
    for line in raw.splitlines():
        heading = re.match(r'^(#{1,6})\s+(.*\S)\s*$', line)
        if heading:
            body = '\n'.join(buffer).strip()
            for piece in _split_long(f'{section}\n{body}' if body else section):
                if len(piece) >= MIN_CHUNK_CHARS:
                    chunks.append(piece)
            section = f'{title} > {heading.group(2).strip()}'
            buffer = []
        else:
            buffer.append(line)
    body = '\n'.join(buffer).strip()
    for piece in _split_long(f'{section}\n{body}' if body else section):
        if len(piece) >= MIN_CHUNK_CHARS:
            chunks.append(piece)
    return chunks


def _crop_kb_chunks():
    """Render the static crop knowledge base as searchable prose."""
    from .crop_kb import ALTERNATE_CROPS, CROP_KB, LOW_WATER_CROPS
    chunks = []
    for key in sorted(CROP_KB):
        entry = CROP_KB[key] or {}
        names = entry.get('names') or {}
        alias = ' / '.join(str(v) for v in names.values() if isinstance(v, str))
        months = [m for m in (entry.get('planting_months') or []) if 1 <= int(m) <= 12]
        stages = entry.get('critical_stages') or {}
        water = {'low': 'low water need', 'medium': 'medium water need',
                 'high': 'high water need'}.get(entry.get('water_need'), '')
        priority = ('It is a low-water crop and is protected first when water is '
                    'short.' if key in LOW_WATER_CROPS else
                    'It needs more water than the low-water crops, so it is the one '
                    'to ration last during a drought.')
        text = (
            f'Crop profile: {key} ({alias}). '
            f'Advised sowing / planting months: '
            + (', '.join(f'{_MONTHS_EN[int(m) - 1]} ({m})' for m in sorted(months)) or 'not defined')
            + f'. Water requirement: {water}. '
            f'Growth stages most damaged by water stress: '
            + '; '.join(f'{lang}: {value}' for lang, value in stages.items() if value)
            + f'. {priority}')
        chunks.append(text)
    alternate = '; '.join(f'{lang}: {value}' for lang, value in ALTERNATE_CROPS.items())
    chunks.append(
        'Water prioritisation during drought: crops with a low water need are '
        'protected first. Low-water crops on this platform: '
        + ', '.join(LOW_WATER_CROPS)
        + f'. Suggested alternates when water is short - {alternate}.')
    return chunks


INTERNAL_DOCS_DENYLIST = {
    'MIGRATION_GUIDE.md',
    'DATABASE_SETUP.md',
    'OPERATIONS_GUIDE.md',
    'DB_QUICK_REFERENCE.md',
    'DATABASE_IMPLEMENTATION_SUMMARY.md',
    'USER_TRACKING_GUIDE.md',
    'PYTORCH_SETUP.md',
    'INDEX_AND_DELIVERY_SUMMARY.md',
    'IMPLEMENTATION_SUMMARY.md',
}


def load_corpus():
    """Every retrievable chunk: {id, source, title, text}."""
    corpus = []
    directory = _docs_dir()
    if directory.is_dir():
        for path in sorted(directory.glob('*.md')):
            if path.name in INTERNAL_DOCS_DENYLIST:
                continue
            for position, text in enumerate(_markdown_chunks(path)):
                corpus.append({
                    'id': f'{path.name}#{position}',
                    'source': f'docs/{path.name}',
                    'title': path.stem.replace('_', ' ').title(),
                    'kind': 'document',
                    'text': text,
                })
    for position, text in enumerate(_crop_kb_chunks()):
        crop = text.split('Crop profile: ')[-1].split(' (')[0] if 'Crop profile: ' in text else 'water'
        corpus.append({
            'id': f'crop_kb/{crop}',
            'source': 'crop knowledge base',
            'title': f'Crop profile: {crop}',
            'kind': 'crop',
            'text': text,
        })
    return corpus


def corpus_signature(chunks=None):
    """Identity of the corpus + embedding model, for cache invalidation."""
    chunks = chunks if chunks is not None else load_corpus()
    parts = [INDEX_VERSION, rag_config()['model']]
    for chunk in chunks:
        parts.append(f"{chunk['id']}:{hashlib.sha1(chunk['text'].encode()).hexdigest()[:12]}")
    return hashlib.sha1('|'.join(parts).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Embeddings (local Ollama)
# --------------------------------------------------------------------------- #
def embedding_model_installed(url=None):
    cfg = rag_config()
    url = url or cfg['url']
    try:
        resp = requests.get(f'{url}/api/tags', timeout=5)
        if resp.status_code != 200:
            return False
        names = [m.get('name', '') for m in resp.json().get('models', [])]
    except Exception as exc:                       # noqa: BLE001
        logger.warning('rag: Ollama unreachable at %s (%s)', url, exc)
        return False
    wanted = cfg['model']
    return any(name == wanted or name.startswith(f'{wanted}:') for name in names)


_BATCH_EMBED = {'supported': None}
_BATCH_LOCK = threading.Lock()


def _embed_batch(texts, model, cfg):
    """POST /api/embed, remembering servers that only speak the legacy API."""
    with _BATCH_LOCK:
        supported = _BATCH_EMBED['supported']
    if supported is not False:
        try:
            resp = requests.post(f"{cfg['url']}/api/embed",
                                 json={'model': model, 'input': list(texts)},
                                 timeout=cfg['embed_timeout'])
            if resp.status_code == 200:
                with _BATCH_LOCK:
                    _BATCH_EMBED['supported'] = True
                return resp.json().get('embeddings') or []
            if resp.status_code == 404:
                with _BATCH_LOCK:
                    _BATCH_EMBED['supported'] = False
            else:
                logger.warning('rag: /api/embed HTTP %s for model %s',
                               resp.status_code, model)
                return None
        except Exception as exc:                   # noqa: BLE001
            logger.warning('rag: embedding call failed (%s: %s)', type(exc).__name__, exc)
            return None
    return None


def _embed_legacy(texts, model, cfg):
    """One request per text, for Ollama builds without /api/embed."""
    out = []
    for text in texts:
        try:
            resp = requests.post(f"{cfg['url']}/api/embeddings",
                                 json={'model': model, 'prompt': text},
                                 timeout=cfg['embed_timeout'])
            if resp.status_code != 200:
                logger.warning('rag: /api/embeddings HTTP %s for model %s',
                               resp.status_code, model)
                return None
            out.append(resp.json().get('embedding') or [])
        except Exception as exc:                   # noqa: BLE001
            logger.warning('rag: legacy embedding failed (%s)', exc)
            return None
    return out


def embed_texts(texts, model=None):
    """Embed `texts` with the local embedding model, L2-normalised.

    Returns a float32 matrix, or None when embeddings are unavailable so the
    caller can fall back to lexical retrieval only.
    """
    cfg = rag_config()
    model = model or cfg['model']
    if not texts or not model:
        return None
    vectors = _embed_batch(texts, model, cfg)
    if vectors is None:
        vectors = _embed_legacy(texts, model, cfg)
    if not vectors or len(vectors) != len(texts) or not vectors[0]:
        return None
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _embed_query(text):
    vector = embed_texts([text])
    return None if vector is None else vector[0]


# --------------------------------------------------------------------------- #
# Index
# --------------------------------------------------------------------------- #
class DocumentIndex:
    """Hybrid chunk index: TF-IDF always, dense vectors when available."""

    def __init__(self, chunks, vectors=None, signature=''):
        self.chunks = chunks
        self.vectors = vectors
        self.signature = signature
        self._vectoriser = None
        self._lexical_matrix = None

    # -- lexical ----------------------------------------------------------- #
    def _ensure_lexical(self):
        if self._lexical_matrix is not None:
            return
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            vectoriser = TfidfVectorizer(
                analyzer='word', lowercase=True, sublinear_tf=True,
                token_pattern=r'[\w\u0600-\u06FF]+', max_features=60000)
            matrix = vectoriser.fit_transform([c['text'] for c in self.chunks])
        except Exception as exc:                   # noqa: BLE001
            logger.warning('rag: lexical index unavailable (%s)', exc)
            return
        self._vectoriser = vectoriser
        self._lexical_matrix = matrix

    def _lexical_scores(self, query):
        self._ensure_lexical()
        if self._lexical_matrix is None or self._vectoriser is None:
            return np.zeros(len(self.chunks), dtype=np.float32)
        try:
            row = self._vectoriser.transform([query])
            scores = (self._lexical_matrix @ row.T).toarray().ravel()
        except Exception as exc:                   # noqa: BLE001
            logger.warning('rag: lexical scoring failed (%s)', exc)
            return np.zeros(len(self.chunks), dtype=np.float32)
        return scores.astype(np.float32)

    # -- dense ------------------------------------------------------------- #
    def _dense_scores(self, query):
        vector = _embed_query(query)
        if vector is None or self.vectors is None:
            return None
        if self.vectors.shape[0] != len(self.chunks):
            return None
        return (self.vectors @ vector).astype(np.float32)

    # -- search ------------------------------------------------------------ #
    def search(self, query, top_k=4, crop=None, depth=12, max_per_source=2):
        """Reciprocal-rank fusion of the lexical and dense rankings.

        At most `max_per_source` chunks of the same document are returned so a
        single long file cannot fill the whole prompt.
        """
        if not self.chunks or not query:
            return []
        probe = query
        if crop:
            probe = f'{crop} {query}'
        lexical = self._lexical_scores(probe)
        dense = self._dense_scores(probe)
        rankings = [np.argsort(-lexical)]
        if dense is not None:
            rankings.append(np.argsort(-dense))
        fused = np.zeros(len(self.chunks), dtype=np.float32)
        for ranking in rankings:
            for position, chunk_index in enumerate(ranking[:max(depth, top_k) * 2]):
                fused[chunk_index] += 1.0 / (RRF_K + position + 1)
        best = np.zeros(len(self.chunks), dtype=np.float32)
        if dense is not None:
            best = np.maximum(best, dense)
        best = np.maximum(best, lexical)
        order = np.argsort(-fused)
        hits = []
        per_source = {}
        for chunk_index in order:
            if fused[chunk_index] <= 0:
                break
            if best[chunk_index] <= 0:
                continue
            chunk = self.chunks[int(chunk_index)]
            seen = per_source.get(chunk['source'], 0)
            if seen >= max_per_source:
                continue
            per_source[chunk['source']] = seen + 1
            hits.append({
                'source': chunk['source'],
                'title': chunk['title'],
                'kind': chunk.get('kind', 'document'),
                'text': chunk['text'],
                'score': round(float(fused[chunk_index]), 5),
                'relevance': round(float(best[chunk_index]), 4),
            })
            if len(hits) >= top_k:
                break
        return hits

    # -- persistence ------------------------------------------------------- #
    def save(self, signature):
        directory = _index_dir()
        directory.mkdir(parents=True, exist_ok=True)
        payload = {'signature': signature, 'version': INDEX_VERSION,
                   'model': rag_config()['model'], 'chunks': self.chunks}
        tmp = directory / 'chunks.json.tmp'
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        tmp.replace(directory / 'chunks.json')
        if self.vectors is not None:
            np.save(str(directory / 'vectors.npy'), self.vectors)

    @classmethod
    def load(cls):
        directory = _index_dir()
        chunks_path = directory / 'chunks.json'
        if not chunks_path.is_file():
            return None
        try:
            payload = json.loads(chunks_path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            logger.warning('rag: index file unreadable (%s)', exc)
            return None
        if payload.get('version') != INDEX_VERSION:
            return None
        vectors = None
        vectors_path = directory / 'vectors.npy'
        if payload.get('model') == rag_config()['model'] and vectors_path.is_file():
            try:
                vectors = np.load(str(vectors_path))
            except Exception as exc:               # noqa: BLE001
                logger.warning('rag: vectors unreadable (%s)', exc)
                vectors = None
        return cls(payload.get('chunks') or [], vectors,
                   payload.get('signature', ''))


_INDEX = None
_INDEX_LOCK = threading.Lock()


def build_index(embed=True, persist=True):
    """Build a fresh index from the corpus."""
    cfg = rag_config()
    chunks = load_corpus()
    signature = corpus_signature(chunks)
    vectors = embed_texts([c['text'] for c in chunks]) if (embed and cfg['model']) else None
    index = DocumentIndex(chunks, vectors, signature)
    if persist:
        try:
            index.save(signature)
        except OSError as exc:
            logger.warning('rag: could not persist index (%s)', exc)
    return index


def get_index(embed=None):
    """The shared index, loaded from disk or built on first use."""
    global _INDEX
    if not rag_config()['enabled']:
        return None
    if _INDEX is not None:
        return _INDEX
    with _INDEX_LOCK:
        if _INDEX is not None:
            return _INDEX
        cfg = rag_config()
        index = DocumentIndex.load()
        if index is None or index.signature != corpus_signature():
            logger.info('rag: building index (embed=%s)', bool(embed or cfg['auto_embed']))
            index = build_index(embed=bool(embed or cfg['auto_embed']))
        _INDEX = index
        return _INDEX


def reset_index_cache():
    global _INDEX
    _INDEX = None


# --------------------------------------------------------------------------- #
# Live data digests
# --------------------------------------------------------------------------- #
def _round(value, digits=1):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _month_label(when):
    if not when:
        return ''
    return f'{_MONTHS_EN[when.month - 1]} {when.year}'


def _digest_cache_key(region):
    from django.core.cache import cache
    from ..models import ClimateMetrics, DroughtIndices, RemoteSensingMetrics
    try:
        signature = '|'.join(str(model.objects.count()) for model in
                             (ClimateMetrics, DroughtIndices, RemoteSensingMetrics))
    except Exception:                              # noqa: BLE001
        signature = 'unknown'
    return f'rag:data:{region.id}:{date.today().isoformat()}:{hashlib.sha1(signature.encode()).hexdigest()[:8]}'


def data_digests(region, question='', limit=3):
    """Short factual digests from the live tables for `region`."""
    if region is None:
        return []
    from django.core.cache import cache
    from ..models import ClimateMetrics, DroughtIndices, RemoteSensingMetrics
    key = _digest_cache_key(region)
    cached = cache.get(key)
    if cached is not None:
        return cached[:limit]
    out = []
    today = date.today()
    try:
        window = today - timedelta(days=rag_config()['data_window_days'])
        rows = list(ClimateMetrics.objects.filter(
            region=region, measurement_date__gte=window
        ).values_list('measurement_date', 'rainfall_mm', 'temperature_max_c'))
        by_month = {}
        for when, rain, tmax in rows:
            key = (when.year, when.month)
            entry = by_month.setdefault(key, {'rain': 0.0, 'days': 0, 'wet': 0, 'tmax': []})
            if rain is not None:
                entry['rain'] += float(rain)
                if float(rain) > 0:
                    entry['wet'] += 1
            if tmax is not None:
                entry['tmax'].append(float(tmax))
            entry['days'] += 1
        ranked = []
        for (year, month), entry in by_month.items():
            if entry['days'] < 5:
                continue
            ranked.append((entry['rain'], year, month, entry))
        if ranked:
            driest = min(ranked, key=lambda item: item[0])
            wettest = max(ranked, key=lambda item: item[0])
            def _describe(item):
                rain, year, month, entry = item
                peak = max(entry['tmax']) if entry['tmax'] else None
                return (f'{_month_label(date(year, month, 1))}: {rain:.1f} mm total '
                        f'aggregated over {entry["days"]} station-days, '
                        f'{entry["wet"]} of them with rain'
                        + (f', hottest station-day {peak:.1f} C' if peak else ''))
            out.append(f'Recent rainfall extremes for {region.name} - driest month: '
                       + _describe(driest) + '; wettest month: ' + _describe(wettest) + '.')
    except Exception as exc:                       # noqa: BLE001
        logger.warning('rag: climate digest failed (%s: %s)', type(exc).__name__, exc)
    try:
        latest = (RemoteSensingMetrics.objects.filter(region=region)
                  .order_by('-measurement_date').first())
        if latest is not None:
            parts = [f'{label} {_round(getattr(latest, field), 2)}'
                     for label, field in (('NDVI', 'ndvi'), ('NDWI', 'ndwi'),
                                          ('land surface temperature C',
                                           'land_surface_temperature_c'),
                                          ('satellite soil moisture %',
                                           'satellite_soil_moisture_percent'))
                     if getattr(latest, field, None) is not None]
            if parts:
                out.append(f'Latest satellite observation for {region.name} on '
                           f'{_month_label(latest.measurement_date)}: '
                           + ', '.join(parts) + '.')
    except Exception as exc:                       # noqa: BLE001
        logger.warning('rag: satellite digest failed (%s: %s)', type(exc).__name__, exc)
    try:
        indices = list(DroughtIndices.objects.filter(region=region)
                       .order_by('-measurement_date')
                       .values('measurement_date', 'spei_1month', 'spei_3month',
                               'spei_12month', 'drought_severity_class')[:6])
        usable = [row for row in indices if row['spei_3month'] is not None]
        if usable:
            newest, oldest = usable[0], usable[-1]
            out.append(
                f'SPEI-3 history for {region.name}: '
                + ', '.join(f'{_month_label(r["measurement_date"])} {float(r["spei_3month"]):.2f}'
                            + (f' ({r["drought_severity_class"]})'
                               if r['drought_severity_class'] else '')
                            for r in usable)
                + f'. Change over the period: '
                  f'{float(newest["spei_3month"]) - float(oldest["spei_3month"]):+.2f}.')
    except Exception as exc:                       # noqa: BLE001
        logger.warning('rag: drought digest failed (%s: %s)', type(exc).__name__, exc)
    try:
        cache.set(key, out, 900)
    except Exception:                              # noqa: BLE001
        pass
    return out[:limit]


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def context_numbers(context):
    """Numeric values that retrieved context is allowed to introduce."""
    values = []
    excerpts = list(context.get('documents') or []) + list(context.get('data') or [])
    for hit in excerpts:
        text = hit.get('text', '') if isinstance(hit, dict) else str(hit)
        for token in re.findall(r'-?\d+(?:[.,]\d+)?', text):
            try:
                values.append(float(token.replace(',', '.')))
            except ValueError:
                pass
    return values


def gather(question, lang='en', crop=None, region=None):
    """Assemble the retrieved context handed to the LLM.

    Never raises: a retrieval failure returns an empty context so the answer
    pipeline continues with the deterministic facts only.
    """
    cfg = rag_config()
    empty = {'documents': [], 'data': [], 'numbers': [],
             'signature': '', 'dense': False, 'chunks': 0}
    if not cfg['enabled'] or not question:
        return empty
    documents = []
    signature = ''
    dense = False
    chunks = 0
    try:
        index = get_index()
    except Exception as exc:                       # noqa: BLE001
        logger.warning('rag: index unavailable (%s: %s)', type(exc).__name__, exc)
        index = None
    if index is not None and index.chunks:
        chunks = len(index.chunks)
        signature = index.signature
        dense = index.vectors is not None
        try:
            documents = index.search(question, top_k=cfg['top_k'], crop=crop,
                                     depth=cfg['lexical_depth'],
                                     max_per_source=cfg['max_per_source'])
        except Exception as exc:                   # noqa: BLE001
            logger.warning('rag: search failed (%s: %s)', type(exc).__name__, exc)
            documents = []
    data = []
    try:
        data = data_digests(region, question)
    except Exception as exc:                       # noqa: BLE001
        logger.warning('rag: data retrieval failed (%s: %s)', type(exc).__name__, exc)
    documents = [hit for hit in documents if hit['score'] >= cfg['min_score']]
    context = {'documents': documents, 'data': data, 'signature': signature,
               'dense': dense, 'chunks': chunks}
    context['numbers'] = context_numbers(context)
    return context


def prompt_block(context):
    """Render the retrieved context for the LLM prompt."""
    documents = context.get('documents') or []
    data = context.get('data') or []
    if not documents and not data:
        return ''
    cfg = rag_config()
    parts = []
    budget = cfg['max_chars']
    if data:
        joined = ' '.join(data)
        parts.append('LIVE DATA (authoritative, from the database): ' + joined)
        budget -= len(joined)
    for position, hit in enumerate(documents, 1):
        if budget <= 0:
            break
        text = hit['text'][:budget]
        budget -= len(text)
        parts.append(f'[Context {position}]: {text}')
    return '\n'.join(parts)


def sources_for(context):
    """Compact source list for the API payload / UI."""
    out = []
    for hit in (context.get('documents') or []):
        out.append({'title': hit['title'], 'source': hit['source'],
                    'kind': hit['kind'], 'relevance': hit['relevance']})
    if context.get('data'):
        out.append({'title': 'Live project database', 'source': 'database',
                    'kind': 'data', 'relevance': 1.0})
    return out
