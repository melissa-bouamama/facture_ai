# Image de service : API et interface de démo factur-ia, avec OCR français et validation schematron.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-fra \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install ".[ocr,api,schematron,bench]"

RUN useradd --create-home facturia
USER facturia

EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# LLM optionnel : pointer vers un serveur compatible OpenAI (Ollama, vLLM, Mistral…)
# ENV FACTURIA_LLM_BASE_URL=http://host.docker.internal:11434/v1 FACTURIA_LLM_MODEL=qwen2.5:7b-instruct
CMD ["uvicorn", "facturia.api:app", "--host", "0.0.0.0", "--port", "8000"]
