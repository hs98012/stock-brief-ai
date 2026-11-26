"""Fail closed before any production stage can receive evaluation labels."""
import os
import re
from pathlib import Path
import sys


def validate_input(data):
    if set(data) != {'documents', 'questions', 'configuration'}:
        raise ValueError('Prediction input fields are not allowlisted')
    for question in data['questions']:
        if set(question) != {'id', 'document_id', 'question'}:
            raise ValueError('Question contains labels or scoring metadata')
        if not all(isinstance(value, str) for value in question.values()):
            raise ValueError('Question fields must be strings')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', question['id']):
            raise ValueError('Unsafe question ID')
    if set(data['configuration']) != {'effective_environment', 'top_k', 'rerank', 'diagnostics', 'transport'}:
        raise ValueError('Prediction configuration contains forbidden metadata')
    config = data['configuration']
    if config['top_k'] != 5 or type(config['rerank']) is not bool or type(config['diagnostics']) is not bool:
        raise ValueError('Invalid fixed ranking configuration')
    if set(config['transport']) != {'ollama_base_url', 'paddle_structure_url'}:
        raise ValueError('Unknown transport field')
    if not all(isinstance(value, str) for value in config['transport'].values()):
        raise ValueError('Transport values must be strings')
    if not all(isinstance(value, str) for value in config['effective_environment'].values()):
        raise ValueError('Environment values must be strings')
    allowed_environment = {'EMBEDDING_PROVIDER', 'EMBEDDING_MODEL', 'EMBEDDING_DIMENSIONS',
        'OCR_DPI', 'PADDLE_STRUCTURE_TIMEOUT_SECONDS', 'ANALYSIS_LLM_PROVIDER',
        'ANALYSIS_LLM_FALLBACK_PROVIDER', 'GENERATION_MODEL', 'GEMINI_MODEL',
        'GENERATION_TEMPERATURE', 'OLLAMA_GENERATION_TIMEOUT_SECONDS', 'GEMINI_TIMEOUT_SECONDS',
        'GEMINI_MAX_ATTEMPTS', 'GEMINI_RETRY_BASE_DELAY_SECONDS'}
    if set(data['configuration']['effective_environment']) - allowed_environment:
        raise ValueError('Unknown prediction environment field')
    allowed_document = {'document_id', 'company_name', 'stock_code', 'issuer',
        'published_at', 'original_filename', 'pdf_path', 'sha256'}
    for document in data['documents']:
        if set(document) != allowed_document:
            raise ValueError('Document contains labels or review annotations')


def install_guard(root, stage):
    """Protect semantic label reads, including symlinks and low-level os.open.

    A dedicated process also runs inside a macOS file sandbox. This audit hook
    provides a portable second layer; it is not an OS security boundary alone.
    """
    root, stage = Path(root).resolve(), Path(stage).resolve()
    denied = (root/'evals', root/'docs')
    def guard(event, args):
        if event != 'open' or not args or isinstance(args[0], int):
            return
        path = Path(os.fsdecode(args[0])).resolve()
        if any(path.is_relative_to(folder) for folder in denied) and not path.is_relative_to(stage):
            raise PermissionError('Prediction process cannot read evaluation or review files')
    sys.addaudithook(guard)
