"""Crop knowledge base for the Farmer Assistant.

Static, reviewable agronomic facts for the main crops of the regions.
Planting windows are calendar months (Tunisia / northern Morocco patterns).
Water need drives prioritisation advice during drought (low-water crops are
protected first / recommended as alternates).
"""

# water_need: 'low' | 'medium' | 'high'  (used for prioritisation + alternates)
# planting_months: list of calendar month ints when sowing/planting is advised
# critical_stages: growth stages when water stress hurts yield most
CROP_KB = {
    'tomato': {
        'names': {'en': 'tomato', 'fr': 'tomate', 'ar': 'الطماطم', 'ar2': ['طماطم', 'بندورة']},
        'planting_months': [2, 3, 8, 9],
        'water_need': 'high',
        'critical_stages': {
            'en': 'flowering and fruit set',
            'fr': 'floraison et nouaison',
            'ar': 'الإزهار وتكوين الثمار',
        },
    },
    'pepper': {
        'names': {'en': 'pepper', 'fr': 'piment', 'ar': 'الفلفل', 'ar2': ['فلفل']},
        'planting_months': [3, 4],
        'water_need': 'high',
        'critical_stages': {
            'en': 'flowering and fruit enlargement',
            'fr': 'floraison et grossissement des fruits',
            'ar': 'الإزهار وتكبير الثمار',
        },
    },
    'olive': {
        'names': {'en': 'olive', 'fr': 'olivier', 'ar': 'الزيتون', 'ar2': ['زيتون']},
        'planting_months': [11, 12, 1, 2, 3],
        'water_need': 'low',
        'critical_stages': {
            'en': 'pit hardening (early summer)',
            'fr': 'durcissement du noyau (début d été)',
            'ar': 'تصلب النواة (بداية الصيف)',
        },
    },
    'citrus': {
        'names': {'en': 'citrus', 'fr': 'agrumes', 'ar': 'الحمضيات', 'ar2': ['برتقال', 'ليمون']},
        'planting_months': [2, 3, 4, 10, 11],
        'water_need': 'high',
        'critical_stages': {
            'en': 'flowering and fruit enlargement',
            'fr': 'floraison et grossissement des fruits',
            'ar': 'الإزهار وتكبير الثمار',
        },
    },
    'wheat': {
        'names': {'en': 'wheat', 'fr': 'blé', 'ar': 'القمح', 'ar2': ['حبوب']},
        'planting_months': [11, 12],
        'water_need': 'medium',
        'critical_stages': {
            'en': 'tillering and grain filling',
            'fr': 'tallage et remplissage du grain',
            'ar': 'التفريع وامتلاء الحبة',
        },
    },
    'barley': {
        'names': {'en': 'barley', 'fr': 'orge', 'ar': 'الشعير', 'ar2': ['شعير']},
        'planting_months': [11, 12],
        'water_need': 'low',
        'critical_stages': {
            'en': 'tillering and grain filling',
            'fr': 'tallage et remplissage du grain',
            'ar': 'التفريع وامتلاء الحبة',
        },
    },
    'alfalfa': {
        'names': {'en': 'alfalfa', 'fr': 'luzerne', 'ar': 'البرسيم', 'ar2': ['علف', 'فصصة']},
        'planting_months': [10, 11, 2, 3],
        'water_need': 'high',
        'critical_stages': {
            'en': 'each regrowth after cutting',
            'fr': 'chaque repousse après coupe',
            'ar': 'كل إعادة نمو بعد الجز',
        },
    },
}

# Crops recommended as drought-resilient alternates (low water need)
LOW_WATER_CROPS = ['olive', 'barley']

# Alternate crop suggestion shown in planting advice under drought
ALTERNATE_CROPS = {'en': 'barley or olive trees', 'fr': 'l orge ou l olivier',
                   'ar': 'الشعير أو أشجار الزيتون'}


def find_crop(text):
    """Detect a crop key mentioned in the question (any language).

    Matching is delegated to the NLU layer so accents, Arabic marks and small
    typos ("tomatos", "oliv") are tolerated.
    """
    from .assistant_nlu import match_crop
    return match_crop(text)
