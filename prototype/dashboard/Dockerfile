FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY __init__.py app.py data.py story.py history.py why.py recording.py /app/dashboard/
COPY static /app/dashboard/static
USER 10001:10001
CMD ["uvicorn", "dashboard.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-server-header"]
