FROM python:3.12-slim

WORKDIR /app

# requirements.txt is now `-e .`, an editable install of this project itself
# -- pip needs pyproject.toml and the package source present to build it, so
# those have to be copied in before the install step, not after. Editable
# (not a regular `pip install .`) matters here too: the package resolves
# spec/data/samples/web relative to iso8583_decoder/__file__ at runtime, and
# an editable install keeps __file__ pointing at this source tree rather
# than a copy in site-packages disconnected from those sibling directories.
COPY pyproject.toml requirements.txt ./
COPY iso8583_decoder ./iso8583_decoder
RUN pip install --no-cache-dir -r requirements.txt

COPY spec ./spec
COPY data ./data
COPY samples ./samples
COPY web ./web

EXPOSE 8000

CMD ["sh", "-c", "uvicorn iso8583_decoder.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
