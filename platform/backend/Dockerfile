FROM python:3.11-slim

WORKDIR /app

# Layer-cache dependency install separately from app code.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# No CMD/ENTRYPOINT here — this image serves both the `backend` (uvicorn)
# and `worker` (arq) docker-compose services, which set their own
# `command:`. See ../docker-compose.yml.
