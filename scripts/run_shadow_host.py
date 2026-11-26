#!/usr/bin/env python3
"""Run shadow audit against local DB/Ollama; no secrets printed or persisted."""
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url

ROOT=Path(__file__).resolve().parents[1]
configuration=dotenv_values(ROOT/'.env')
database_url=configuration.get('DATABASE_URL')
if database_url:
    url=make_url(database_url)
    if url.host not in ('postgres','localhost','127.0.0.1'):
        raise RuntimeError('Unexpected local DB host')
    url=url.set(host='localhost',port=int(configuration.get('POSTGRES_HOST_PORT') or 5432))
else:
    url=URL.create('postgresql+psycopg',username=configuration.get('POSTGRES_USER') or 'stock_brief',
        password=configuration.get('POSTGRES_PASSWORD') or 'change-me-for-local-development',
        host='localhost',port=int(configuration.get('POSTGRES_HOST_PORT') or 5432),
        database=configuration.get('POSTGRES_DB') or 'stock_brief')
os.environ['DATABASE_URL']=url.render_as_string(hide_password=False)
os.environ['OLLAMA_BASE_URL']='http://localhost:11434'
os.environ['PADDLE_STRUCTURE_URL']='http://127.0.0.1:8090'
for key in ('EMBEDDING_PROVIDER','EMBEDDING_MODEL','EMBEDDING_DIMENSIONS'):
    if configuration.get(key):os.environ[key]=configuration[key]
from audit_shadow import main
main()
