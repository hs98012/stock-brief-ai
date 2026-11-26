"""Isolated CPU document structure inference; no database or generation access."""
import asyncio
import hashlib
import io
import json
import platform
import subprocess
import sys
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from PIL import Image
from paddleocr import PPStructureV3

MODEL = "PP-StructureV3/PP-OCRv5_mobile_det/korean_PP-OCRv5_mobile_rec"
pipeline = None
lock = asyncio.Lock()
fingerprint = None


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _fingerprint():
    root = Path('/root/.paddlex/official_models')
    if not root.is_dir():
        raise RuntimeError('Paddle model files are unavailable')
    model_files = {str(path.relative_to(root)): _sha256(path)
                   for path in sorted(root.rglob('*')) if path.is_file()}
    if not model_files:
        raise RuntimeError('Paddle model files are empty')
    freeze = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True)
    options = dict(device='cpu', enable_mkldnn=False, cpu_threads=2,
                   use_doc_orientation_classify=False, use_doc_unwarping=False,
                   use_textline_orientation=False, use_formula_recognition=False,
                   use_seal_recognition=False, use_chart_recognition=False,
                   text_recognition_model_name='korean_PP-OCRv5_mobile_rec',
                   text_detection_model_name='PP-OCRv5_mobile_det',
                   text_recognition_batch_size=1, language='korean', render_dpi=216)
    payload = dict(model=MODEL, options=options, python_version=platform.python_version(),
                   paddlepaddle_version=version('paddlepaddle'),
                   paddleocr_version=version('paddleocr'), paddlex_version=version('paddlex'),
                   pip_freeze_sha256=hashlib.sha256(freeze.encode()).hexdigest(),
                   model_files=model_files)
    payload['sha256'] = hashlib.sha256(json.dumps(payload, sort_keys=True,
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return payload


@asynccontextmanager
async def lifespan(app):
    global pipeline, fingerprint
    pipeline = await asyncio.to_thread(
        PPStructureV3, device="cpu", enable_mkldnn=False, cpu_threads=2,
        use_doc_orientation_classify=False, use_doc_unwarping=False,
        use_textline_orientation=False, use_formula_recognition=False,
        use_seal_recognition=False, use_chart_recognition=False,
        text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
        text_detection_model_name="PP-OCRv5_mobile_det",text_recognition_batch_size=1,
    )
    fingerprint = await asyncio.to_thread(_fingerprint)
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    if pipeline is None or fingerprint is None:
        raise HTTPException(503, "Models not ready")
    return {"status": "ok", "model": MODEL, "paddleocr": "3.3.2", "device": "cpu"}


@app.get('/fingerprint')
def get_fingerprint():
    if fingerprint is None:
        raise HTTPException(503, 'Models not ready')
    return fingerprint


@app.post("/parse")
async def parse(request: Request):
    body = await request.body()
    if len(body) > 40 * 1024 * 1024:
        raise HTTPException(413, "Page image too large")
    try:
        image = Image.open(io.BytesIO(body)).convert("RGB")
    except Exception as exc:
        raise HTTPException(422, "Invalid image") from exc
    if image.width * image.height > 30_000_000:
        raise HTTPException(413, "Page resolution too large")
    # Paddle's ndarray input is BGR. Serialize inference: shared CPU predictors
    # are not thread-safe and simultaneous PDF requests must not duplicate models.
    async with lock:
        results = await asyncio.to_thread(lambda: list(pipeline.predict(np.asarray(image)[:, :, ::-1])))
    return {"model": MODEL, "paddleocr": "3.3.2", "width": image.width,
            "height": image.height, "fingerprint_sha256": fingerprint['sha256'],
            "result": results[0].json["res"]}
