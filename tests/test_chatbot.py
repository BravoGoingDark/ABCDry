import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()

from dashboard.services.farmer_assistant import get_assistant_answer

questions = [
    ("What is this website about?", "en"),
    ("How do I upload data?", "en"),
    ("What does the map color mean?", "en"),
    ("Comment utiliser le tableau de bord?", "fr"),
    ("Where can I see drought forecasts?", "en"),
    ("How do I export data to Excel?", "en"),
    ("What is SPEI?", "en"),
    ("Who can use this platform?", "en"),
]

for q, lang in questions:
    try:
        r = get_assistant_answer(q, lang=lang)
        intent = r.get("intent", "?")
        engine = r.get("engine", "?")
        detected_lang = r.get("lang", "?")
        answer = r.get("answer", "")
        print(f"Q: {q[:60]}")
        print(f"  Intent={intent} | Engine={engine} | Lang={detected_lang}")
        print(f"  A: {answer[:200]}")
        print()
    except Exception as exc:
        print(f"Q: {q[:60]}")
        print(f"  ERROR: {exc}")
        print()
