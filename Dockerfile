FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the full repository (examples/scripts/config templates included).
COPY . /app

# Run the Python discovery orchestrator by default.
# Other modes (webapp/shell) can override the command/entrypoint in `make`.
ENTRYPOINT ["python", "-m", "isilon_discovery"]
CMD ["--inventory", "inventory.yaml"]

