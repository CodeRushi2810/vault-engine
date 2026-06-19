FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY core/ core/
COPY scripts/ scripts/
COPY bootup.py .

# We map the data directory as a volume to persist state across container restarts
RUN mkdir -p data

EXPOSE 8000
EXPOSE 8001

CMD ["python", "bootup.py"]
