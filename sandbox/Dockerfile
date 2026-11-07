# Code-execution sandbox: runs Python the agent writes (data science + ML stack).
# Isolation comes from docker-compose.yml: internal-only network (no internet),
# read-only filesystem, non-root, no capabilities, CPU/memory/process limits.
FROM python:3.12-slim

RUN pip install --no-cache-dir numpy pandas scipy scikit-learn matplotlib seaborn statsmodels

WORKDIR /srv
COPY server.py ./
USER nobody
EXPOSE 8000
CMD ["python", "server.py"]
