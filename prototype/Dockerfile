FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir /data /audit-logs /audit-keys /checkpoints \
    && chown 10001:10001 /data /audit-logs /audit-keys /checkpoints
COPY --chown=10001:10001 common.py storage.py gateway.py blue.py model.py demo_isolation.py init_env.py manage.py ./
COPY --chown=10001:10001 audit_format.py audit_store.py audit_collector.py audit_forwarder.py verify_audit.py demo_audit_tamper.py ./
COPY --chown=10001:10001 range_feedback.py ./
COPY --chown=10001:10001 tests/ ./tests/
USER 10001:10001
CMD ["uvicorn", "gateway:factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
