"""Launch the production API against the fixed persistent E2E target; no migration."""
import os
from restore_e2e_persistent import ROOT, ARCHIVE, engine, guard
import sys

if '--low-memory' in sys.argv:
    os.environ['STOCK_BRIEF_LOW_MEMORY'] = '1'

ALLOWED = {'GEMINI_API_KEY', 'GEMINI_MODEL', 'GEMINI_TIMEOUT_SECONDS',
    'GEMINI_MAX_ATTEMPTS', 'GEMINI_RETRY_BASE_DELAY_SECONDS',
    'ANALYSIS_LLM_PROVIDER', 'ANALYSIS_LLM_FALLBACK_PROVIDER', 'GENERATION_MODEL',
    'OLLAMA_GENERATION_TIMEOUT_SECONDS', 'GENERATION_TEMPERATURE'}
for line in (ROOT / '.env').read_text().splitlines():
    key, separator, value = line.partition('=')
    if separator and key in ALLOWED:
        os.environ[key] = value.strip().strip('"').strip("'")

target = engine()
with target.connect() as connection:
    guard(connection)
os.environ['DATABASE_URL'] = target.url.render_as_string(hide_password=False)
os.environ['DATA_DIR'] = str(ARCHIVE / 'data')
os.environ['OLLAMA_BASE_URL'] = 'http://127.0.0.1:11434'
os.environ['EMBEDDING_MODEL'] = 'bge-m3'
os.environ['EMBEDDING_DIMENSIONS'] = '1024'
os.environ['CORS_ORIGINS'] = 'http://localhost:13002,http://127.0.0.1:13002,http://127.0.0.1:13003'
# External evidence disclosure was blocked by approval review. Local E2E only.
os.environ['ANALYSIS_LLM_PROVIDER'] = 'ollama'
os.environ['ANALYSIS_LLM_FALLBACK_PROVIDER'] = 'none'
os.environ['ANALYSIS_EXTERNAL_ENABLED'] = '0'
os.environ['ANALYSIS_OLLAMA_FALLBACK_ENABLED'] = '0'

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=18002, log_level='info', workers=1)
