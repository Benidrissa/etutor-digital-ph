FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir transformers torch scipy fastapi uvicorn[standard] huggingface_hub

COPY server.py /app/server.py

EXPOSE 5050

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "5050"]
