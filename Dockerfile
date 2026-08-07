FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY iso8583_decoder ./iso8583_decoder
COPY spec ./spec
COPY data ./data
COPY samples ./samples
COPY web ./web

EXPOSE 8000

CMD ["sh", "-c", "uvicorn iso8583_decoder.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
