FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /worker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY disable_unused_chart.py .
RUN python disable_unused_chart.py
COPY app.py .
ENV PADDLE_PDX_MODEL_SOURCE=BOS OMP_NUM_THREADS=4 DISABLE_MODEL_SOURCE_CHECK=True
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1"]
