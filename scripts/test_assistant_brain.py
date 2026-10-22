"""End-to-end test of the new grounded assistant brain.

Runs a battery of questions through the real pipeline (facts -> rules -> LLM
-> numeric validation) and prints intent, engine, model, latency and answer.

Usage:
  python scripts/test_assistant_brain.py                 # auto-detected model
  python scripts/test_assistant_brain.py gemma3:1b       # force a model
"""
import os
import sys
import time

PROJECT = r'c:/Users/Taha/Desktop/CURSORAGRI - Copy - Copy'
sys.path.insert(0, PROJECT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')

if len(sys.argv) > 1:
    os.environ['ASSISTANT_LLM_MODEL'] = sys.argv[1]

# Write a UTF-8 report so Arabic/French text is never mangled by the console.
REPORT = os.path.join(PROJECT, 'scripts', 'brain_report.txt')
report = open(REPORT, 'w', encoding='utf-8')


def emit(line=''):
    print(line.encode('ascii', 'replace').decode('ascii'))
    report.write(line + '\n')
    report.flush()

import django  # noqa: E402

django.setup()

from django.core.cache import cache  # noqa: E402

from dashboard.services.assistant_brain import (  # noqa: E402
    build_facts, classify_intent, installed_models, resolve_model,
    validate_numbers)

emit(f'installed models : {installed_models()}')
emit(f"resolved model   : {resolve_model(force=True) or '(none - template only)'}")

QUESTIONS = [
    ('en', 'Is drought expected next month?'),
    ('en', 'My wheat leaves are turning yellow, why?'),
    ('en', 'Hello, who are you?'),
    ('en', 'What is NDVI and why does it matter?'),
    ('en', 'Show me rainfall for July 2019'),
    ('en', 'When should I irrigate my tomatoes?'),
    ('fr', 'Quand dois-je irriguer ?'),
    ('ar', 'هل يُتوقع جفاف الشهر القادم؟'),
]

cache.clear()   # exercise the cold path for every question

from dashboard.services.farmer_assistant import get_assistant_answer  # noqa: E402

for lang, question in QUESTIONS:
    started = time.time()
    result = get_assistant_answer(question, region_id=None, lang=lang,
                                  use_llm=True)
    elapsed = time.time() - started
    emit('-' * 78)
    emit(f'Q ({lang}): {question}')
    emit(f'   intent={result["intent"]} engine={result["engine"]} '
         f'model={result["model"]} cache={result["from_cache"]} {elapsed:.1f}s')
    if result.get('engine_reason'):
        emit(f'   fallback reason: {result["engine_reason"]}')
    emit('   A: ' + result['answer'].replace('\n', '\n      '))

emit('-' * 78)
emit('numeric guard test:')
facts = build_facts(region_id=None)
emit('   fabricated "risk 68/100 with 1234 mm" -> '
     + str(validate_numbers('Drought risk is 68/100 with 1234 mm of rain', facts)))
emit('   grounded   "risk 20/100"             -> '
     + str(validate_numbers('Drought risk is 20/100 today', facts)))
emit('')
emit('full report written to scripts/brain_report.txt')

