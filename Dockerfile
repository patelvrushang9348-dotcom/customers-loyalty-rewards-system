FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Provide SECRET_KEY, CODE_PEPPER, ADMIN_USERNAME, ADMIN_PASSWORD, DATABASE_PATH via environment.
# Mount a volume at /data and set DATABASE_PATH=/data/loyalty.db to persist data.
EXPOSE 8000
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "run:app"]
