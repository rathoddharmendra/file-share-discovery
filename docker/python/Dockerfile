FROM python:3.11-slim

WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /workspace/requirements.txt

COPY isilon_discovery /workspace/isilon_discovery
COPY webapp /workspace/webapp
COPY scripts /workspace/scripts
COPY examples /workspace/examples

CMD ["python", "-m", "isilon_discovery", "--inventory", "/workspace/config/inventory.yaml"]
