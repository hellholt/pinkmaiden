FROM --platform=linux/amd64 python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app.py .
COPY static/ static/

EXPOSE 8642

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8642", "--log-level", "info"]
