# Бот Деревня Тигрит — общая БД с Игра (ensure-user API), пул через tigrit_shared
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tigrit_shared ./tigrit_shared
COPY app.py db_async.py prompts.py llm.py ./
ENV PYTHONPATH=/app
CMD ["python", "app.py"]
