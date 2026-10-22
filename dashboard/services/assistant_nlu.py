"""Question understanding for the AgroAI farmer assistant.

Everything here is deterministic and offline: no model call, no network.

Three jobs:

* normalise what the user typed (case, punctuation, French accents, Arabic
  diacritics/tatweel and alef/ya/ta-marbuta variants) so matching is stable;
* match the message against crop names, region names and intent keywords with
  prefix + fuzzy tolerance, so "irigate" or "tomatos" still lands on the
  right intent;
* resolve short or anaphoric follow-ups ("and for olives?", "next month?")
  against the conversation so the crop, the region and the intent survive
  from one turn to the next.
"""
import difflib
import re
import unicodedata

FUZZY = 0.82
FUZZY_SHORT = 0.75
FUZZY_MIN_LEN = 5

_ARABIC_MARKS = re.compile(r'[\u064B-\u065F\u0670\u06D6-\u06ED\u0640]')
_LETTER_VARIANTS = str.maketrans({
    '\u0623': '\u0627', '\u0625': '\u0627', '\u0622': '\u0627',
    '\u0649': '\u064A', '\u0629': '\u0647',
    '\u0624': '\u0648', '\u0626': '\u064A',
})
_KEEP = re.compile(r'[^0-9a-z\u0600-\u06FF]+')
_WHITESPACE = re.compile(r'\s+')

FOLLOWUP_LEADS = {
    'and', 'also', 'then', 'what', 'about', 'why', 'how', 'when', 'where',
    'same', 'more', 'less', 'still', 'it', 'that', 'this', 'next', 'else',
    'instead', 'ok', 'okay', 'yes', 'no', 'so', 'now', 'but', 'well', 'if',
}
ARABIC_FOLLOWUP_LEADS = {
    '\u0648', '\u0627\u0648', '\u062B\u0645', '\u0645\u0627', '\u0645\u0627\u0630\u0627',
    '\u0643\u064A\u0641', '\u0644\u0645\u0627\u0630\u0627', '\u0645\u062A\u0649',
    '\u0643\u0645', '\u0647\u0644', '\u0627\u064A\u0636\u0627', '\u0628\u0639\u062F',
    '\u0647\u0630\u0647', '\u0647\u064A', '\u0627\u0646\u0647',
    '\u0644\u0643\u0646', '\u0627\u0630\u0627', '\u0643\u0645\u0627', '\u0627\u064A',
}
REGION_DENYLIST = ('verify', 'test', 'copy', 'tmp')
REGION_DEPENDENT = ('irrigation', 'planting', 'drought_status', 'historical',
                    'crop_care', 'water_reduction')


def normalize_text(text):
    """Fold a message to a comparable form: case/accents/marks/punctuation."""
    if not text:
        return ''
    folded = unicodedata.normalize('NFKD', str(text))
    folded = _ARABIC_MARKS.sub('', folded)
    folded = ''.join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.translate(_LETTER_VARIANTS).lower()
    return _WHITESPACE.sub(' ', _KEEP.sub(' ', folded)).strip()


def tokenize(text):
    return normalize_text(text).split()


# --------------------------------------------------------------------------- #
# Fuzzy keyword matching
# --------------------------------------------------------------------------- #
# Very common function words. They are one edit away from real keywords
# ("what"/"wheat", "the"/"heat"), so they must never take a fuzzy score.
STOPWORDS = {
    'a', 'about', 'all', 'am', 'an', 'and', 'any', 'are', 'as', 'at', 'be',
    'been', 'but', 'by', 'can', 'could', 'did', 'do', 'does', 'for', 'from',
    'had', 'has', 'have', 'her', 'here', 'his', 'how', 'i', 'if', 'in', 'is',
    'it', 'its', 'me', 'more', 'most', 'my', 'no', 'now', 'of', 'on', 'or',
    'our', 'please', 'shall', 'she', 'should', 'so', 'some', 'such', 'tell',
    'than', 'that', 'the', 'their', 'them', 'then', 'there', 'these', 'they',
    'this', 'those', 'to', 'too', 'us', 'was', 'we', 'were', 'what', 'whats',
    'when', 'where', 'which', 'who', 'why', 'will', 'with', 'would', 'you',
    'your',
}


def _prefix_ok(shorter, longer):
    """A shared prefix only counts as morphology, not as a coincidence.

    "tomatoes"/"tomato" is morphology; "a"/"agrumes" is the French preposition
    "à" landing on the citrus alias.
    """
    return len(shorter) >= 3 and len(shorter) / len(longer) >= 0.5


def _strip_article(word):
    """Arabic definite article, so "القمح" matches the stored name "قمح"."""
    return word[2:] if len(word) > 3 and word[:2] == '\u0627\u0644' else word


def _token_matches(token, needle):
    """1.0 exact, ~0.9 morphological prefix, ~0.85 typo, 0.0 no match.

    Containment that is not a prefix is rejected: "wheat" contains "heat", so
    a fuzzy score must never fire on a word that merely extends the keyword
    somewhere else. Function words are exact-only on both sides: "what" must
    not reach "wheat", and "wheat" must not stand in for the "what" in
    "what is".
    """
    if not needle:
        return 0.0
    if token == needle:
        return 1.0
    shorter, longer = sorted((token, needle), key=len)
    if (token.startswith(needle) or needle.startswith(token)) and _prefix_ok(shorter, longer):
        return 0.9
    if len(token) >= 5 and len(needle) >= 5 and token[:5] == needle[:5]:
        return 0.88  # same root, different inflection: irriguer / irrigat
    if needle in token or token in needle:
        return 0.0
    if abs(len(token) - len(needle)) > 1:
        return 0.0
    if token in STOPWORDS or needle in STOPWORDS:
        return 0.0
    floor = FUZZY if min(len(token), len(needle)) >= FUZZY_MIN_LEN else FUZZY_SHORT
    ratio = difflib.SequenceMatcher(None, token, needle).ratio()
    return ratio if ratio >= floor else 0.0


def keyword_score(text, tokens, keyword):
    """2 = verbatim, 1 = close enough, 0 = no match."""
    keyword = normalize_text(keyword)
    if not keyword or not text:
        return 0
    parts = keyword.split()
    if len(parts) == 1:
        # A single word must start a token, otherwise "heat" fires on "wheat".
        if re.search(r'(?<![a-z])' + re.escape(parts[0]), text):
            return 2
        if any(_token_matches(token, parts[0]) for token in tokens):
            return 1
        return 1 if any(_token_matches(_strip_article(token), parts[0])
                        for token in tokens) else 0
    if keyword in text:
        return 2
    best = [0.0] * len(parts)
    for token in tokens:
        for position, part in enumerate(parts):
            score = _token_matches(token, part)
            if not score:
                score = _token_matches(_strip_article(token), part)
            best[position] = max(best[position], score)
    return 1 if all(score >= 0.85 for score in best) else 0


# --------------------------------------------------------------------------- #
# Intent
# --------------------------------------------------------------------------- #
INTENT_KEYWORDS = (
    ('greeting', ('hello', 'hi ', 'hey', 'bonjour', 'salut', 'bonsoir',
                  '\u0645\u0631\u062D\u0628\u0627', '\u0627\u0644\u0633\u0644\u0627\u0645',
                  '\u0623\u0647\u0644\u0627')),
    ('help', ('who are you', 'what can you do', 'help me', 'your name',
              'qui es-tu', 'que peux-tu', 'aide-moi',
              '\u0645\u0646 \u0623\u0646\u062A', '\u0645\u0627\u0630\u0627 \u062A\u0633\u0637\u0639')),
    ('website_guide', ('website', 'platform', 'site web', 'site internet', 'plateforme',
                       'dashboard', 'tableau de bord',
                       'how to use', 'how do i use', 'how do i navigate', 'how do i find', 'how do i access',
                       'how do i upload', 'how do i export', 'how do i download', 'how do i login',
                       'how do i view the map', 'how do i switch region',
                       'comment utiliser', 'comment naviguer', 'how to navigate',
                       'where can i find', 'where is', 'ou trouver', 'ou est', 'ou se trouve',
                       'interactive map', 'risk map', 'carte interactive', 'carte des risques',
                       'map color', 'map colour', 'color mean', 'colour mean', 'what color', 'what colour',
                       'green mean', 'red mean', 'orange mean', 'yellow mean',
                       'risk score mean', 'risk score work', 'drought score', 'score mean',
                       'data ingestion', 'upload data', 'upload file', 'televerser', 'importer des donnees',
                       'export excel', 'export csv', 'telecharger rapport', 'telecharger excel',
                       'spei outlook', 'previsions spei', 'page', 'pages', 'navigation', 'navigate',
                       'sensor network', 'sensors page', 'liste des capteurs', 'ajouter un capteur',
                       'metrics browser', 'navigateur de metriques', 'tableau de donnees',
                       'formula', 'formulas', 'calculation', 'calculations', 'formule', 'formules', 'calculs',
                       'admin panel', 'panneau d administration', 'connexion', 'login',
                       'apwrs', 'abcdry', 'features', 'fonctionnalites', 'capabilities',
                       'historical trends', 'historical page', 'historical data',
                       'tendances historiques', 'donnees historiques',
                       'how to check', 'how to view', 'how to access', 'how to find',
                       'comment voir', 'comment acceder', 'comment trouver',
                       'who can use', 'who uses', 'for whom', 'for who', 'who is this for',
                       'what can this', 'what does this platform', 'what does the platform',
                       'what does this site', 'what does the site', 'what does this dashboard',
                       'what does this tool', 'what can the platform', 'what can i do here',
                       'pour qui', 'qui peut utiliser', 'a qui est destine',
                       'pour quoi faire', 'a quoi ca sert', 'a quoi sert',
                       '\u0644\u0645\u0646 \u0647\u0630\u0647', '\u0645\u0646 \u064a\u0633\u062a\u062e\u062f\u0645',
                       '\u0645\u0627\u0630\u0627 \u064a\u0645\u0643\u0646 \u0647\u0630\u0627',
                       '\u0644\u0645\u0627\u0630\u0627 \u0647\u0630\u0647 \u0627\u0644\u0645\u0646\u0635\u0629',
                       '\u0645\u0648\u0642\u0639', '\u0645\u0646\u0635\u0629', '\u0644\u0648\u062D\u0629 \u0627\u0644\u062A\u062D\u0643\u0645', '\u0644\u0648\u062D\u0629 \u0627\u0644\u0642\u064A\u0627\u062F\u0629',
                       '\u062E\u0631\u064A\u0637\u0629', '\u062E\u0631\u064A\u0637\u0629 \u062A\u0641\u0627\u0639\u0644\u064A\u0629', '\u062E\u0631\u064A\u0637\u0629 \u0627\u0644\u0645\u062E\u0627\u0637\u0631',
                       '\u0643\u064A\u0641 \u0623\u0633\u062A\u062E\u062F\u0645', '\u0643\u064A\u0641 \u0627\u0633\u062A\u062E\u062F\u0645',
                       '\u0643\u064A\u0641 \u0623\u062A\u0646\u0642\u0644', '\u0643\u064A\u0641 \u0627\u062A\u0646\u0642\u0644',
                       '\u0623\u064A\u0646 \u0623\u062C\u062F', '\u0627\u064A\u0646 \u0627\u062C\u062F',
                       '\u0623\u064A\u0646 \u062A\u0642\u0639', '\u0627\u064A\u0646 \u062A\u0642\u0639',
                       '\u0631\u0641\u0639 \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A', '\u0631\u0641\u0639 \u0645\u0644\u0641', '\u0627\u0633\u062A\u064A\u0631\u0627\u062F \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A',
                       '\u062A\u0635\u062F\u064A\u0631', '\u062A\u0646\u0632\u064A\u0644', '\u062A\u0635\u062F\u064A\u0631 \u0625\u0643\u0633\u0644', '\u062A\u0635\u062F\u064A\u0631 \u0627\u0643\u0633\u0644',
                       '\u062A\u0648\u0642\u0639\u0627\u062A \u0627\u0644\u062C\u0641\u0627\u0641', '\u0635\u0641\u062D\u0629 \u0627\u0644\u062A\u0648\u0642\u0639\u0627\u062A',
                       '\u0627\u0644\u0645\u0633\u062A\u0634\u0639\u0631\u0627\u062A', '\u0627\u0644\u062D\u0633\u0627\u0633\u0627\u062A',
                       '\u0627\u0644\u0645\u0642\u0627\u064A\u064A\u0633', '\u0633\u062C\u0644 \u0627\u0644\u0645\u0642\u0627\u064A\u064A\u0633',
                       '\u0645\u0639\u0627\u062F\u0644\u0627\u062A', '\u0644\u0648\u062D\u0629 \u0627\u0644\u0625\u062F\u0627\u0631\u0629',
                       '\u0645\u0645\u064A\u0632\u0627\u062F', '\u062E\u0635\u0627\u0626\u0635')),
    ('knowledge', ('what is ', 'what are ', 'define', 'meaning of',
                   'explain the', "qu'est-ce", 'definition',
                   'what does spei', 'what does spi', 'what does ndvi',
                   'what does vci', 'what does et0', 'what does et',
                   'what does pdsi', 'what does ndwi',
                   'what is spei', 'what is spi', 'what is ndvi',
                   'what is vci', 'what is et0', 'what is pdsi',
                   'what is et', 'what is ndwi', 'what is eto',
                   'explain spei', 'explain ndvi', 'explain vci',
                   'explain et0', 'explain drought index',
                   'qu est-ce que', 'c est quoi', 'expliquez',
                   '\u0645\u0627 \u0647\u0648', '\u0645\u0627 \u0645\u0639\u0646\u0649',
                   '\u0645\u0627 \u0647\u0648 \u0633\u0628\u064a\u0627\u064a',
                   '\u0645\u0627 \u0647\u0648 \u0645\u0624\u0634\u0631',
                   '\u0643\u064a\u0641 \u064a\u0639\u0645\u0644',
                   '\u0645\u0627 \u0645\u0639\u0646\u0649 \u0645\u0624\u0634\u0631')),
    ('historical', ('history', 'historique', 'last year', 'previous year',
                    'trend since', '\u062A\u0627\u0631\u064A\u062E')),
    ('irrigation', ('irrigat', 'water my', 'watering', 'how much water',
                    'arros', '\u0633\u0642\u064A', '\u0627\u0644\u0631\u064A',
                    '\u0623\u0631\u0648\u064A')),
    ('planting', ('plant', 'sow', 'seed', 'which crop', 'variety',
                   'plantation', 'semis', 'cultiver',
                   '\u0632\u0631\u0627\u0639\u0629', '\u0623\u0632\u0631\u0639',
                   '\u0628\u0630\u0631')),
    ('water_reduction', ('reduce', 'less water', 'save water', 'restriction',
                         '\u00e9conomiser', 'reduire', 'r\u00e9duire',
                         '\u062A\u0631\u0634\u064A\u062F', '\u0627\u0642\u062A\u0635\u0627\u062F',
                         '\u062A\u0642\u0644\u064A\u0644', '\u062A\u0648\u0641\u064A\u0631')),
    ('crop_care', ('care', 'maintain', 'fertiliz', 'fertilis', 'prune',
                   'entretien', 'taille', 'engrais',
                   '\u062A\u0633\u0645\u064A\u062F', '\u062A\u0642\u0644\u064A\u0645',
                   '\u0635\u064A\u0627\u0646\u0629', 'yellow', 'jauniss', 'leaves',
                   'disease', 'pest', 'maladie', '\u0645\u0631\u0636', '\u0627\u0635\u0641\u0631\u0627\u0631')),
    ('soil_moisture', ('soil moisture', 'soil water', 'humidit\u00e9 du sol',
                       'humidite du sol', '\u0631\u0637\u0648\u0628\u0629',
                       '\u0627\u0644\u062A\u0631\u0628\u0629')),
    ('vegetation_health', ('ndvi', 'vci', 'vegetation', 'v\u00e9g\u00e9tation',
                           'greenness', '\u0646\u0628\u0627\u062A', '\u063A\u0637\u0627\u0621')),
    ('rainfall', ('rain', 'rainfall', 'pluie', 'pr\u00e9cipitation',
                  'precipitation', '\u0645\u0637\u0631', '\u0623\u0645\u0637\u0627\u0631')),
    ('temperature', ('temperature', 'heat', 'chaleur', 'temp\u00e9rature',
                     '\u062D\u0631\u0627\u0631\u0629')),
    ('drought_status', ('drought', 'draught', 's\u00e9cheresse', 'secheresse', 'risk',
                        'risque', 'outlook', 'forecast', 'next month', 'spei',
                        'spi', '\u062C\u0641\u0627\u0641', '\u0627\u0644\u0648\u0636\u0639',
                        '\u062E\u0637\u0631', '\u062A\u0648\u0642\u0639', '\u0627\u0644\u062D\u0627\u0644\u0629')),
)
_TABLE = {}


def _keyword_table():
    table = _TABLE.get('keywords')
    if table is None:
        table = tuple((intent, tuple(normalize_text(word) for word in words))
                      for intent, words in INTENT_KEYWORDS)
        _TABLE['keywords'] = table
    return table


def match_intent(text):
    """Return (intent, scores); 'freeform' when nothing matched.

    Priority rules (in order):
      1. website_guide  – any website/navigation keyword wins immediately.
      2. knowledge      – a definitional question wins when its score is at
                         least 80 % of the top competing score; this stops
                         "What is SPEI?" from being re-routed to
                         drought_status just because SPEI also fired there.
      3. highest scorer – normal winner-take-all.
    """
    normalised = normalize_text(text)
    tokens = normalised.split()
    scores = {}
    if normalised:
        for intent, keywords in _keyword_table():
            total = sum(keyword_score(normalised, tokens, word) for word in keywords)
            if total:
                scores[intent] = total
    if not scores:
        return 'freeform', scores
    if 'website_guide' in scores and scores['website_guide'] >= 1:
        return 'website_guide', scores
    top = max(scores.values())
    if 'knowledge' in scores and scores['knowledge'] >= top * 0.80:
        return 'knowledge', scores
    return max(scores, key=scores.get), scores


def classify_intent(text):
    """The single best intent for a message ('freeform' when unclear)."""
    return match_intent(text)[0]


def matched_keywords(text, intent):
    """Which keywords of `intent` fired for this message."""
    normalised = normalize_text(text)
    tokens = normalised.split()
    if not normalised or not intent:
        return []
    table = dict(_keyword_table())
    return [word for word in table.get(intent, ())
            if keyword_score(normalised, tokens, word)]


# Phrases that describe *when*, not *what*. A message built only from these
# keeps the topic of the previous turn instead of switching to the outlook.
TEMPORAL_KEYWORDS = {
    'next month', 'next week', 'next year', 'next 7 days', 'next 30 days',
    'next 3 months', 'next season', 'this month', 'this week', 'tomorrow',
    'the month after', 'coming month', 'future months',
    '\u0627\u0644\u0634\u0647\u0631 \u0627\u0644\u0642\u0627\u062F\u0645',
    '\u0627\u0644\u0634\u0647\u0631 \u0627\u0644\u0642\u0627\u062F\u0645',
    '\u0627\u0644\u0634\u0647\u0631 \u0627\u0644\u0642\u0627\u062F\u0645\u061F',
}


# --------------------------------------------------------------------------- #
# Crops
# --------------------------------------------------------------------------- #
def match_crop(text):
    """Detect a crop key mentioned in the message, tolerating typos."""
    from .crop_kb import CROP_KB
    normalised = normalize_text(text)
    if not normalised:
        return None
    tokens = normalised.split()
    best_score = 0
    best_key = None
    for key, crop in CROP_KB.items():
        names = [key]
        for value in ((crop or {}).get('names') or {}).values():
            if isinstance(value, str):
                names.append(value)
            elif isinstance(value, (list, tuple)):
                names.extend(item for item in value if isinstance(item, str))
        score = max((keyword_score(normalised, tokens, name) for name in names),
                    default=0)
        if score == 2:
            return key
        if score > best_score:
            best_score, best_key = score, key
    return best_key if best_score else None


# --------------------------------------------------------------------------- #
# Regions
# --------------------------------------------------------------------------- #
def usable_regions(regions):
    return [r for r in regions
            if not any(bad in (getattr(r, 'name', '') or '').lower()
                       for bad in REGION_DENYLIST)]


def match_region(text, regions):
    """The Region named in the message, or None."""
    normalised = normalize_text(text)
    if not normalised:
        return None
    tokens = normalised.split()
    for region in usable_regions(regions):
        name = normalize_text(getattr(region, 'name', ''))
        if not name:
            continue
        if name in normalised:
            return region
        for token in tokens:
            if len(token) >= 4 and _token_matches(token, name):
                return region
    return None


# --------------------------------------------------------------------------- #
# Conversation continuity
# --------------------------------------------------------------------------- #
def is_followup(text, intent='freeform', crop=None, region=None):
    """True when the message reads as a continuation of the previous turn.

    A message that already carries its own intent, crop or region is a
    complete question even when it starts with "what" or "and".
    """
    tokens = tokenize(text)
    if not tokens:
        return True
    if len(tokens) <= 3:
        return True
    if intent != 'freeform' or crop or region:
        return False
    lead = tokens[0]
    return lead in FOLLOWUP_LEADS or lead in ARABIC_FOLLOWUP_LEADS


def _user_turns(history):
    for turn in history or []:
        if not isinstance(turn, dict):
            continue
        if turn.get('role') in ('assistant', 'ai', 'bot'):
            continue
        content = (turn.get('content') or '').strip()
        if content:
            yield content


def conversation_state(history=None, explicit=None, regions=None):
    """The crop / region / intent the conversation is already about."""
    state = {'crop': None, 'region_name': None, 'intent': None}
    if explicit:
        for key in state:
            if explicit.get(key):
                state[key] = explicit[key]
    for content in reversed(list(_user_turns(history))):
        if state['crop'] is None:
            state['crop'] = match_crop(content)
        if state['intent'] is None:
            intent, _ = match_intent(content)
            if intent != 'freeform':
                state['intent'] = intent
        if state['region_name'] is None and regions is not None:
            region = match_region(content, regions)
            if region is not None:
                state['region_name'] = region.name
    return state


def history_mentions_region(history=None, regions=None):
    """Whether any earlier turn already established a region."""
    for content in _user_turns(history):
        if match_region(content, regions or []):
            return True
    return False


def resolve(question, history=None, explicit=None, region_id=None, crop=None,
            regions=None):
    """Effective crop / region / intent for this message.

    Explicit values always win. Otherwise the message is parsed, and whatever
    it does not mention is inherited from the conversation when the message
    reads as a follow-up.
    """
    if regions is None:
        from ..models import Region
        regions = list(Region.objects.all())

    parsed_intent, _ = match_intent(question)
    parsed_crop = match_crop(question)
    parsed_region = match_region(question, regions)
    followup = is_followup(question, intent=parsed_intent, crop=parsed_crop,
                           region=parsed_region)
    state = conversation_state(history, explicit, regions)

    result = {
        'intent': parsed_intent,
        'crop': crop or parsed_crop,
        'region_id': region_id,
        'region': parsed_region,
        'inherited': {'crop': False, 'region': False, 'intent': False},
        'followup': followup,
    }
    if followup:
        if not result['crop'] and state['crop']:
            result['crop'] = state['crop']
            result['inherited']['crop'] = True
        if (result['region_id'] is None and result['region'] is None
                and state['region_name']):
            for region in usable_regions(regions):
                if (region.name or '').lower() == state['region_name'].lower():
                    result['region'] = region
                    result['inherited']['region'] = True
                    break
        if state['intent']:
            temporal_only = False
            if parsed_intent != 'freeform':
                evidence = matched_keywords(question, parsed_intent)
                temporal_only = bool(evidence) and all(
                    word in TEMPORAL_KEYWORDS for word in evidence)
            if (parsed_intent == 'freeform' or temporal_only) and parsed_intent != state['intent']:
                result['intent'] = state['intent']
                result['inherited']['intent'] = True
    return result


# --------------------------------------------------------------------------- #
# Clarification instead of guessing
# --------------------------------------------------------------------------- #
REGION_QUESTION = {
    'en': 'Which region should I answer for? Pick one below.',
    'fr': 'Pour quelle r\u00e9gion dois-je r\u00e9pondre ? Choisissez ci-dessous.',
    'ar': '\u0644\u0623\u064A \u0645\u0646\u0637\u0642\u0629 \u0639\u0644\u0645\u064A \u0623\u0633\u062A\u062C\u064A\u0628\u061F '
          '\u0627\u062E\u062A\u0631 \u0623\u062F\u0646\u0627\u0647.',
}
TOPIC_QUESTION = {
    'en': 'I can answer on drought status, irrigation, planting, crop care, '
          'water saving, rainfall, temperature and satellite indicators. '
          'Which of these do you need?',
    'fr': 'Je peux r\u00e9pondre sur la s\u00e9cheresse, l\u2019irrigation, la plantation, '
          'l\u2019entretien des cultures, l\u2019\u00e9conomie d\u2019eau, la pluie, '
          'la temp\u00e9rature et les indicateurs satellites. Lequel vous int\u00e9resse ?',
    'ar': '\u0623\u0633\u062A\u0637\u064A\u0639 \u0627\u0644\u0625\u062C\u0627\u0628\u0629 \u0639\u0646 '
          '\u0627\u0644\u062C\u0641\u0627\u0641 \u0648\u0627\u0644\u0631\u064A \u0648\u0627\u0644\u0632\u0631\u0627\u0639\u0629 '
          '\u0648\u0639\u0646\u0627\u064A\u0629 \u0627\u0644\u0645\u062D\u0627\u0635\u064A\u0644 '
          '\u0648\u062A\u0631\u0634\u064A\u062F \u0627\u0644\u0645\u0627\u0621 \u0648\u0627\u0644\u0623\u0645\u0637\u0627\u0631 '
          '\u0648\u0627\u0644\u062D\u0631\u0627\u0631\u0629 \u0648\u0645\u0624\u0634\u0631\u0627\u062A \u0627\u0644\u0623\u0642\u0645\u0627\u0631 '
          '\u0627\u0644\u0635\u0646\u0627\u0639\u064A\u0629\u061F \u0623\u064A\u0647\u0627 \u062A\u0641\u0636\u0644\u0644\u0643\u061F',
}
REGION_OPTION = {
    'en': 'What is the drought situation in {name}?',
    'fr': 'Quelle est la situation de la s\u00e9cheresse \u00e0 {name} ?',
    'ar': '\u0645\u0627 \u062D\u0627\u0644\u0629 \u0627\u0644\u062C\u0641\u0627\u0641 \u0641\u064A {name}\u061F',
}
TOPIC_OPTIONS = {
    'en': ('Is drought expected next month?', 'When should I irrigate?',
           'What should I plant this season?', 'How can I save water?',
           'What do the satellite indicators show?'),
    'fr': ('Une s\u00e9cheresse est-elle pr\u00e9vue le mois prochain ?',
           'Quand dois-je irriguer ?', 'Que planter cette saison ?',
           'Comment \u00e9conomiser de l\u2019eau ?',
           'Que montrent les indicateurs satellites ?'),
    'ar': ('\u0647\u0644 \u064A\u062A\u0648\u0642\u0639 \u062C\u0641\u0627\u0641 \u0627\u0644\u0634\u0647\u0631 '
           '\u0627\u0644\u0642\u0627\u062F\u0645\u061F',
           '\u0645\u062A\u0649 \u064A\u062C\u0628 \u0623\u0646 \u0623\u0633\u0642\u064A\u061F',
           '\u0645\u0627\u0630\u0627 \u0623\u0632\u0631\u0639 \u0647\u0630\u0627 \u0627\u0644\u0645\u0648\u0633\u0645\u061F',
           '\u0643\u064A\u0641 \u0623\u0631\u0634\u0651\u062F \u0627\u0644\u0645\u0627\u0621\u061F',
           '\u0645\u0627\u0630\u0627 \u062A\u064F\u0638\u0647\u0631 \u0645\u0624\u0634\u0631\u0627\u062A \u0627\u0644\u0623\u0642\u0645\u0627\u0631 '
           '\u0627\u0644\u0635\u0646\u0627\u0639\u064A\u0629\u061F'),
}


def region_option(name, lang='en', question=''):
    """A self-contained question that keeps the farmer's own wording.

    "When should I irrigate my wheat?" becomes "When should I irrigate my wheat
    in Kairouan?" instead of a generic question that loses the crop and intent.
    """
    base = re.sub(r'\s+', ' ', str(question or '')).strip().strip(' \t?!؟')
    if not base or len(base) > 160:
        return REGION_OPTION[lang].format(name=name)
    if lang == 'fr':
        return f"{base} \u00e0 {name} ?"
    if lang == 'ar':
        return f"{base} \u0641\u064a {name}\u061f"
    return f"{base} in {name}?"


def clarification(kind, lang='en', regions=None, limit=4, question=''):
    """A focused question plus self-contained follow-up questions.

    Returns (text, options) or (None, None) when there is nothing to ask.
    """
    lang = lang if lang in REGION_QUESTION else 'en'
    if kind == 'region':
        names = [r.name for r in usable_regions(regions or [])][:limit]
        if len(names) < 2:
            return None, None
        return (REGION_QUESTION[lang],
                [region_option(name, lang, question) for name in names])
    if kind == 'topic':
        return TOPIC_QUESTION[lang], list(TOPIC_OPTIONS[lang])
    return None, None


def needs_clarification(intent, region_id=None, parsed_region=None, history=None,
                        regions=None, best_relevance=0.0, enabled=True):
    """Whether to ask instead of answering a question we cannot read."""
    if not enabled:
        return None
    if intent in ('greeting', 'help', 'website_guide'):
        return None
    if intent == 'freeform':
        return 'topic' if not best_relevance else None
    if intent in REGION_DEPENDENT and region_id is None and parsed_region is None:
        if not history_mentions_region(history, regions):
            return 'region'
    return None
