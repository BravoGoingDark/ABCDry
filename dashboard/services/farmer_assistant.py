"""Farmer Assistant brain: context builder, intent classifier, rule engine,
trilingual answer templates, and the answer cache.

Design (for scale + trust):
  - Decisions are ALWAYS deterministic code over DB facts (never the LLM).
  - LLM (local Ollama) only re-phrases the computed recommendation.
  - Cache key = (intent, region_id, crop, month, risk_bucket, lang) so
    identical situations share one answer; pre-warmed monthly.
"""
import hashlib
import logging

from django.core.cache import cache

from dashboard.models import DroughtIndices, Region, SpeiForecast
from dashboard.services.crop_kb import (ALTERNATE_CROPS, CROP_KB,
                                        LOW_WATER_CROPS, find_crop)

logger = logging.getLogger(__name__)

CACHE_TTL = 60 * 60 * 24 * 20  # 20 days; refreshed monthly


def _risk_bucket(level):
    return {'Low': 'low', 'Moderate': 'moderate', 'High': 'high',
            'Severe': 'severe', 'Extreme': 'extreme'}.get(level, 'low')


def timezone_month():
    from django.utils import timezone
    return timezone.now().month


def build_context(region_id=None, crop=None, lang='en'):
    """Collect the current facts for a region from our tables."""
    region = None
    if region_id:
        region = Region.objects.filter(id=region_id).first()
    if region is None:
        region = (Region.objects.filter(name__iexact='Ichkeul').first()
                  or Region.objects.first())

    fc = SpeiForecast.objects.filter(region=region).first()

    from dashboard.models import ClimateMetrics
    clim = (ClimateMetrics.objects.filter(region=region)
            .order_by('-measurement_date').first())

    di = (DroughtIndices.objects.filter(region=region, spei_3month__isnull=False)
          .order_by('-measurement_date').first())

    soil = None
    if di is not None and di.spei_3month is not None:
        soil = max(0.0, min(100.0, 50.0 + float(di.spei_3month) * 25.0))

    level_t1 = fc.level_t1 if fc else 'Low'
    prob_t1 = (float(fc.prob_drought_t1)
               if (fc and fc.prob_drought_t1 is not None) else None)
    risk_score = int(fc.score_t1) if fc else 20

    return {
        'region': region,
        'region_name': region.name if region else 'your area',
        'month': timezone_month(),
        'crop': crop,
        'crop_info': CROP_KB.get(crop) if crop else None,
        'level': level_t1,
        'risk_bucket': _risk_bucket(level_t1),
        'risk_score': risk_score,
        'prob_drought': prob_t1,
        'spei_t3_level': (fc.level_t3 if fc else 'Low'),
        'observed_spei': (float(di.spei_3month)
                          if di and di.spei_3month is not None else None),
        'soil_pct': soil,
        'rain_last_month_mm': (float(clim.rainfall_mm)
                               if clim and clim.rainfall_mm is not None else None),
        'et0_mm_day': (float(clim.evapotranspiration_et0_mmday)
                       if clim and clim.evapotranspiration_et0_mmday is not None else None),
        'temp_mean_c': (float(clim.temperature_mean_c)
                        if clim and clim.temperature_mean_c is not None else None),
        'forecast_month': fc.target_month_t1 if fc else None,
    }


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


def decide(context, intent):
    """Deterministic decision -> {'key': cache-suffix, 'facts': {...}}."""
    region_id = context['region'].id if context['region'] else 0
    crop = context['crop'] or 'none'
    month = context['month']
    bucket = context['risk_bucket']
    key = f'{intent}:{region_id}:{crop}:{month}:{bucket}'
    facts = {'region': context['region_name'], 'crop': crop, 'month': month,
             'level': context['level'], 'risk_score': context['risk_score'],
             'prob_drought': context['prob_drought'], 'bucket': bucket}

    if intent == 'irrigation':
        soil = context['soil_pct'] if context['soil_pct'] is not None else 50.0
        need = context['crop_info']['water_need'] if context['crop_info'] else 'medium'
        facts.update({'soil_pct': round(soil), 'water_need': need})
        if bucket in ('severe', 'extreme'):
            act = 'urgent'
        elif bucket == 'high' or (need == 'high' and soil < 55):
            act = 'soon'
        elif bucket == 'moderate' or soil < 65:
            act = 'monitor'
        else:
            act = 'normal'
        facts['action'] = act

    elif intent == 'planting':
        ci = context['crop_info']
        if ci:
            ok_month = month in ci['planting_months']
            facts.update({'ok_month': ok_month,
                          'water_need': ci['water_need'],
                          'critical_stage': ci['critical_stages']})
            if bucket in ('severe', 'extreme'):
                act = ('postpone_or_switch'
                       if (not ok_month or ci['water_need'] == 'high')
                       else 'caution')
            elif bucket == 'high':
                act = 'caution'
            else:
                act = 'go' if ok_month else 'wait_window'
        else:
            if bucket in ('severe', 'extreme'):
                act = 'recommend_low_water'
            elif bucket == 'high':
                act = 'lean_low_water'
            else:
                act = 'normal_choice'
        facts['action'] = act
        facts['low_water'] = LOW_WATER_CROPS
        facts['alternate'] = ALTERNATE_CROPS

    elif intent == 'drought_status':
        facts['spei_t3_level'] = context['spei_t3_level']

    elif intent == 'water_reduction':
        facts['action'] = ('mandatory' if bucket in ('severe', 'extreme')
                           else 'strong' if bucket == 'high'
                           else 'voluntary' if bucket == 'moderate' else 'none')

    else:  # crop_care
        ci = context['crop_info']
        facts['critical_stage'] = ci['critical_stages'] if ci else None
        facts['action'] = ('stress_watch' if bucket in ('high', 'severe', 'extreme')
                           else 'routine')

    return {'key': key, 'facts': facts}

# ------------------------------------------------------------------ #
# Trilingual answer templates (reviewable = trustworthy)
# ------------------------------------------------------------------ #

def _pct(x):
    return f'{int(round(x * 100))}%' if x is not None else 'n/a'


def render_answer(intent, facts, lang):
    L = lang if lang in ('en', 'fr', 'ar') else 'en'
    region = facts['region']
    crop = facts['crop']
    score = facts['risk_score']

    if intent == 'irrigation':
        a = facts['action']
        soil = facts.get('soil_pct')
        if L == 'en':
            m = {
                'urgent': f'Water stress is severe in {region} (risk {score}/100). Irrigate critical crops within 2-3 days, prioritise high-need crops, and irrigate at dawn or dusk to cut losses.',
                'soon': f'Drought risk is high in {region} (risk {score}/100). Plan irrigation within the next 5-7 days for your most valuable crops; check soil moisture first.',
                'monitor': f'Moderate risk in {region} (risk {score}/100). No immediate irrigation needed, but check soil moisture twice a week and be ready to irrigate.',
                'normal': f'Conditions are normal in {region} (risk {score}/100). Keep your usual irrigation schedule and monitor weekly.',
            }
            txt = m.get(a, m['monitor'])
            if soil is not None:
                txt += f' Estimated soil water status: {soil}% of normal.'
        elif L == 'fr':
            m = {
                'urgent': f'Stress hydrique sévère à {region} (risque {score}/100). Irriguez les cultures critiques sous 2-3 jours, priorité aux cultures à forte demande, tôt le matin ou en soirée.',
                'soon': f'Risque de sécheresse élevé à {region} (risque {score}/100). Prévoyez l irrigation dans les 5-7 jours pour vos cultures les plus précieuses après contrôle de l humidité du sol.',
                'monitor': f'Risque modéré à {region} (risque {score}/100). Pas d irrigation immédiate nécessaire, mais contrôlez l humidité du sol deux fois par semaine.',
                'normal': f'Conditions normales à {region} (risque {score}/100). Gardez votre calendrier d irrigation habituel.',
            }
            txt = m.get(a, m['monitor'])
            if soil is not None:
                txt += f' État estimé de l eau du sol : {soil}% de la normale.'
        else:
            m = {
                'urgent': f'الإجهاد المائي شديد في {region} (الخطر {score}/100). اسقِ المحاصيل الحرجة خلال 2-3 أيام مع الأولوية للمحاصيل عالية الاستهلاك، وفي الفجر أو المساء لتقليل الفاقد.',
                'soon': f'خطر الجفاف مرتفع في {region} (الخطر {score}/100). خطّط للري خلال 5-7 أيام لأهم محاصيلك بعد فحص رطوبة التربة.',
                'monitor': f'خطر متوسط في {region} (الخطر {score}/100). لا حاجة فورية للري، لكن افحص رطوبة التربة مرتين أسبوعياً وكن مستعداً.',
                'normal': f'الظروف طبيعية في {region} (الخطر {score}/100). حافظ على جدول الري المعتاد وراقب أسبوعياً.',
            }
            txt = m.get(a, m['monitor'])
            if soil is not None:
                txt += f' حالة التربة المائية التقديرية: {soil}% من الطبيعي.'
        return txt

    if intent == 'drought_status':
        prob = facts.get('prob_drought')
        t3 = facts.get('spei_t3_level', 'Low')
        if L == 'en':
            s = f'Current drought level in {region}: {facts["level"]} (risk score {score}/100).'
            if prob is not None:
                s += f' Probability of drought next month: {_pct(prob)}.'
            s += f' The 3-month outlook is directional only: conditions are expected to persist or evolve gradually ({t3}).'
        elif L == 'fr':
            s = f'Niveau de sécheresse actuel à {region} : {facts["level"]} (score {score}/100).'
            if prob is not None:
                s += f' Probabilité de sécheresse le mois prochain : {_pct(prob)}.'
            s += f' La perspective à 3 mois est uniquement indicative : poursuite ou évolution graduelle attendue ({t3}).'
        else:
            s = f'مستوى الجفاف الحالي في {region}: {facts["level"]} (درجة الخطر {score}/100).'
            if prob is not None:
                s += f' احتمالية الجفاف الشهر القادم: {_pct(prob)}.'
            s += f' توقعات 3 أشهر إرشادية فقط: يُتوقع استمرار الحالة أو تطورها التدريجي ({t3}).'
        return s

    if intent == 'water_reduction':
        a = facts['action']
        if L == 'en':
            m = {'mandatory': f'Water savings are required in {region} (risk {score}/100): prioritise food crops, stop watering non-essential areas, use drip where possible and mulch to cut evaporation.',
                 'strong': f'Strongly recommended: reduce non-essential watering in {region} (risk {score}/100) and switch to drip/mulching to stretch supplies.',
                 'voluntary': f'Optional savings: modest reductions build a buffer in {region} (risk {score}/100); mulching alone cuts losses notably.',
                 'none': f'No special restrictions needed in {region} (risk {score}/100); normal efficient practices (drip, morning watering) are enough.'}
        elif L == 'fr':
            m = {'mandatory': f'Économies d eau requises à {region} (risque {score}/100) : priorité aux cultures vivrières, arrêt de l arrosage non essentiel, goutte-à-goutte et paillage.',
                 'strong': f'Fortement recommandé : réduire l arrosage non essentiel à {region} (risque {score}/100), passer au goutte-à-goutte et pailler.',
                 'voluntary': f'Économies facultatives : des réductions modérées créent une réserve à {region} (risque {score}/100) ; le paillage réduit déjà fortement les pertes.',
                 'none': f'Pas de restrictions nécessaires à {region} (risque {score}/100) ; les bonnes pratiques habituelles suffisent.'}
        else:
            m = {'mandatory': f'ترشيد إلزامي في {region} (الخطر {score}/100): أولوية للمحاصيل الغذائية، إيقاف ري المساحات غير الأساسية، التقطير والنشارة.',
                 'strong': f'موصى به بشدة: تقليل ري غير الأساسيات في {region} (الخطر {score}/100) والتحول للتقطير مع النشارة.',
                 'voluntary': f'ترشيد اختياري: تخفيضات معتدلة تبني احتياطياً في {region} (الخطر {score}/100)؛ النشارة وحدها تقل الفاقد.',
                 'none': f'لا حاجة لقيود خاصة في {region} (الخطر {score}/100)؛ الممارسات الفعالة المعتادة كافية.'}
        return m.get(a, m['voluntary'])

    if intent == 'crop_care':
        stage = facts.get('critical_stage')
        if L == 'en':
            if stage:
                return f'For {crop} in {region}: protect the critical stage ({stage}) from water stress; risk is {score}/100, so keep moisture stable there and mulch.'
            return f'General care in {region} (risk {score}/100): keep soil moisture stable, mulch, and avoid pruning or fertilising during drought stress.'
        if L == 'fr':
            if stage:
                return f'Pour {crop} à {region} : protégez la période critique ({stage}) du stress hydrique ; risque {score}/100, gardez l humidité stable et paillez.'
            return f'Entretien général à {region} (risque {score}/100) : humidité stable, paillage, éviter taille et fertilisation pendant le stress.'
        if stage:
            return f'لـ {crop} في {region}: احمِ المرحلة الحرجة ({stage}) من الإجهاد المائي؛ الخطر {score}/100، حافظ على رطوبة مستقرة واستخدم النشارة.'
        return f'العناية العامة في {region} (الخطر {score}/100): رطوبة مستقرة، والنشارة، وتجنّب التقليم والتسميد أثناء الإجهاد.'

    # intent == 'planting'
    a = facts['action']
    alt = facts.get('alternate', {}).get(L, '')
    if L == 'en':
        m = {
            'go': f'Good window: planting {crop} this month is appropriate in {region}, and drought risk is manageable (risk {score}/100). Ensure water for its critical stage.',
            'wait_window': f'{crop.capitalize()} is best planted in other months in {region}; current risk is acceptable (risk {score}/100) but the timing is off. Ask me about the right month.',
            'caution': f'Cautious: drought risk is elevated (risk {score}/100). You may still plant {crop} if you can secure irrigation, especially during its critical stage.',
            'postpone_or_switch': f'Not recommended now: severe drought in {region} (risk {score}/100). Postpone planting {crop} or switch to drought-tolerant options such as {alt}.',
            'recommend_low_water': f'With severe drought in {region} (risk {score}/100), favour low-water crops this season, such as {alt}.',
            'lean_low_water': f'Drought risk is elevated (risk {score}/100); lean toward lower-water crops like {alt}, or plant with secure irrigation.',
            'normal_choice': f'Conditions allow your usual crop choice in {region} (risk {score}/100). Ask me about a specific crop for its window.',
        }
    elif L == 'fr':
        m = {
            'go': f'Bonne fenêtre : planter {crop} ce mois est approprié à {region}, risque gérable ({score}/100). Assurez l eau pour la période critique.',
            'wait_window': f'{crop.capitalize()} se plante plutôt à d autres mois à {region} ; le risque est acceptable ({score}/100) mais le calendrier non. Demandez-moi le bon mois.',
            'caution': f'Prudence : risque élevé ({score}/100). La plantation de {crop} reste possible si l irrigation est assurée, surtout à la période critique.',
            'postpone_or_switch': f'Déconseillé maintenant : sécheresse sévère à {region} ({score}/100). Reportez la plantation de {crop} ou choisissez des cultures tolérantes comme {alt}.',
            'recommend_low_water': f'Avec une sécheresse sévère à {region} ({score}/100), privilégiez les cultures à faible besoin comme {alt} cette saison.',
            'lean_low_water': f'Risque élevé ({score}/100) ; orientez-vous vers des cultures économes comme {alt}, ou plantez avec irrigation sécurisée.',
            'normal_choice': f'Les conditions permettent votre choix habituel à {region} ({score}/100). Demandez-moi pour une culture précise.',
        }
    else:
        m = {
            'go': f'وقت مناسب: زراعة {crop} هذا الشهر مناسبة في {region}، والخطر قابل للإدارة ({score}/100). جهّز الماء لمرحلتها الحرجة.',
            'wait_window': f'الأفضل زراعة {crop} في أشهر أخرى في {region}؛ الخطر مقبول ({score}/100) لكن التوقيت غير مناسب. اسألني عن الشهر المناسب.',
            'caution': f'بحذر: خطر الجفاف مرتفع ({score}/100). يمكن الزراعة إذا ضمنت الري، خاصة في المرحلة الحرجة.',
            'postpone_or_switch': f'غير موصى به الآن: جفاف شديد في {region} ({score}/100). أجّل زراعة {crop} أو اختر بدائل مقاومة للجفاف مثل {alt}.',
            'recommend_low_water': f'مع الجفاف الشديد في {region} ({score}/100)، فضّل هذا الموسم محاصيل قليلة الاستهلاك مثل {alt}.',
            'lean_low_water': f'الخطر مرتفع ({score}/100)؛ اتجه لمحاصيل أقل استهلاكاً مثل {alt}، أو ازرع مع ضمان الري.',
            'normal_choice': f'الظروف تسمح باختيارك المعتاد في {region} ({score}/100). اسألني عن محصول محدد.',
        }
    return m.get(a, m['normal_choice'])


# ------------------------------------------------------------------ #
# Answer assembly with cache + optional Ollama voice
# ------------------------------------------------------------------ #

def get_assistant_answer(question, region_id=None, crop=None, lang='en',
                         use_llm=True, history=None, conversation=None):
    """Delegate to the grounded assistant brain (facts -> rules -> LLM).

    Kept as the public entry point: views, tasks and pre-warming call this.
    The brain builds facts from the project database, applies the
    deterministic drought/agronomy rules, and lets the local LLM explain them
    in the user's language - validating every number against the facts.
    ``conversation`` carries the crop/region the client already knows about so
    short follow-ups keep their context.
    """
    from dashboard.services.assistant_brain import answer_question
    return answer_question(question, region_id=region_id, crop=crop, lang=lang,
                           use_llm=use_llm, history=history,
                           conversation=conversation)


def _llm_rephrase(base_answer, lang):
    """Optional Ollama re-phrasing; never breaks the answer."""
    try:
        from dashboard.prediction_engine.llm_explainer import DroughtLLMExplainer
        explainer = DroughtLLMExplainer()
        if not explainer.available:
            return None
        import requests
        lang_name = {'en': 'English', 'fr': 'French', 'ar': 'Arabic'}.get(lang, 'English')
        prompt = ('You are an agricultural assistant. Rewrite the following '
                  f'advice in {lang_name} in a warm, simple tone for a farmer. '
                  'Keep every fact, number and recommendation EXACTLY the same. '
                  'Maximum 4 sentences. No lists, no markdown.\n\nAdvice: '
                  + base_answer)
        resp = requests.post(f'{explainer.ollama_url}/api/generate',
                             json={'model': explainer.model_name, 'prompt': prompt,
                                   'stream': False, 'temperature': 0.4,
                                   'num_predict': 200},
                             timeout=15)
        if resp.status_code == 200:
            return (resp.json().get('response') or '').strip() or None
        return None
    except Exception:
        return None


def prewarm_answers():
    """Pre-generate the common answers (called by the monthly task)."""
    from dashboard.services.assistant_brain import prewarm_answers as _prewarm
    return _prewarm()


def suggestions(lang='en'):
    from dashboard.services.assistant_brain import suggestions as _suggestions
    return _suggestions(lang)
