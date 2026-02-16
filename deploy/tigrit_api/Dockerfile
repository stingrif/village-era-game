# Tigrit API: tigrit_shared + backend (FastAPI), данные из PostgreSQL
FROM python:3.11-slim
WORKDIR /app
COPY tigrit_shared ./tigrit_shared
COPY backend ./backend
RUN pip install --no-cache-dir -r backend/requirements.txt
ENV PYTHONPATH=/app
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
