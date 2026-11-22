FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --create-home --uid 10001 olap
COPY olap ./olap
COPY sql ./sql
COPY web ./web
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER olap

CMD ["python", "-m", "uvicorn", "olap.app:app", "--host", "0.0.0.0", "--port", "8000"]
