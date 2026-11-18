# The Unreliable Assistant: API service image (deployment.md).
# Streamlit workbench is NOT included; it is a developer tool.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf

WORKDIR /app

# 1. Dependencies only (cached until pyproject.toml changes). Read from pyproject so the list lives in one place.
COPY pyproject.toml ./
RUN python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb'))['project']; \
open('/tmp/requirements.txt','w').write('\n'.join(d['dependencies'] + d['optional-dependencies']['models']))" \
 && pip install --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install --extra-index-url https://pypi.org/simple -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# 2. Application code. Changing code does not reinstall dependencies.
COPY src ./src
RUN pip install --no-deps .

# 3. Runtime data: the knowledge vault is read from /app/knowledge_vault (settings.PROJECT_ROOT).
COPY knowledge_vault ./knowledge_vault
COPY mcp_config.json ./

RUN useradd --create-home --uid 10001 assistant && mkdir -p /models && chown assistant /models
USER assistant

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2).status==200 else 1)"

# --workers 1: state (cache, HITL, audit) is in-process until Postgres/Redis land (gaps.md § 1.3).
CMD ["uvicorn", "assistant.api.app:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
