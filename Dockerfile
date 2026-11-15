FROM python:3.14-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 DATABASE_PATH=/app/data/aselli.sqlite3
COPY app.py schema.sql ./
COPY web ./web
RUN useradd --create-home aselli && mkdir /app/data && chown aselli:aselli /app/data
USER aselli
EXPOSE 8000
CMD ["python", "app.py"]
