FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SUNSPOT_HOME=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY sunspot_pipeline ./sunspot_pipeline
COPY app ./app
COPY .streamlit ./.streamlit
COPY streamlit_app.py .

# Raw snapshots, run records and the archive go to /data, so mount a volume there
# to keep them between container restarts.
RUN useradd --create-home appuser && mkdir /data && chown appuser /data
USER appuser
VOLUME /data

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
