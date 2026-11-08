FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home userbot && mkdir /app/data && chown userbot:userbot /app/data
COPY userbot ./userbot
USER userbot
CMD ["python", "-m", "userbot"]
