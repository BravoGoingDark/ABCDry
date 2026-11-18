"""Farmer Assistant brain: context builder, intent classifier, rule engine,
trilingual answer templates, and the answer cache.

Design (for scale + trust):
  - Decisions are ALWAYS deterministic code over DB facts (never the LLM).
  - LLM (local Ollama) only re-phrases the computed recommendation.
  - Cache key = (intent, region_id, crop, month, risk_bucket, lang) so
    identical situations share one answer; pre-warmed monthly.
"""
import logging



logger = logging.getLogger(__name__)

CACHE_TTL = 60 * 60 * 24 * 20  # 20 days; refreshed monthly


def classify_intent(question):
    q = (question or '').lower()
    kw = {
        'irrigation': ['irrigat', 'water my', 'watering', 'how much water',
                       'arros', 'سقي', 'الري', 'أروي', 'ماء'],
        'planting': ['plant', 'sow', 'seed', 'which crop', 'variety',
                     'plantation', 'semis', 'cultiver', 'زراعة', 'أزرع',
                     'بذر', 'غرس', 'موسم'],
        'water_reduction': ['reduce', 'less water', 'save water', 'restriction',
                            'économiser', 'reduire', 'réduire', 'تقليل',
                            'توفير', 'ترشيد', 'اقتصاد'],
        'crop_care': ['care', 'maintain', 'fertiliz', 'fertilis', 'prune',
                      'entretien', 'taille', 'engrais', 'عناية', 'تسميد',
                      'تقليم', 'صيانة'],
        'drought_status': ['drought', 'situation', 'status', 'condition',
                           'secheresse', 'sécheresse', 'risk', 'risque',
                           'جفاف', 'الوضع', 'الظروف', 'الحالة', 'خطر'],
    }
    scores = {i: sum(1 for k in ks if k in q) for i, ks in kw.items()}
    best = max(scores, key=scores.get)
    return best if scores.get(best, 0) > 0 else 'drought_status'


# ------------------------------------------------------------------ #
# Trilingual answer templates (reviewable = trustworthy)
# ------------------------------------------------------------------ #

def _pct(x):
    return f'{int(round(x * 100))}%' if x is not None else 'n/a'


# ------------------------------------------------------------------ #
# Answer assembly with cache + optional Ollama voice
# ------------------------------------------------------------------ #

def get_assistant_answer(question, region_id=None, crop=None, lang='en',
                         use_llm=True, history=None, conversation=None, farm=None):
    """Delegate to the grounded assistant brain (facts -> rules -> LLM).

    Kept as the public entry point: views, tasks and pre-warming call this.
    The brain builds facts from the project database, applies the
    deterministic drought/agronomy rules, and lets the local LLM explain them
    in the user's language - validating every number against the facts.
    ``conversation`` carries the crop/region the client already knows about so
    short follow-ups keep their context. ``farm`` (the asking farmer's own
    parcel) lets farm questions be answered from the farm's data.
    """
    from dashboard.services.assistant_brain import answer_question
    return answer_question(question, region_id=region_id, crop=crop, lang=lang,
                           use_llm=use_llm, history=history,
                           conversation=conversation, farm=farm)


def prewarm_answers():
    """Pre-generate the common answers (called by the monthly task)."""
    from dashboard.services.assistant_brain import prewarm_answers as _prewarm
    return _prewarm()


def suggestions(lang='en', farm=None):
    if farm is not None:
        from dashboard.services.farm_qa import suggestions as _farm_suggestions
        return _farm_suggestions(lang)
    from dashboard.services.assistant_brain import suggestions as _suggestions
    return _suggestions(lang)
