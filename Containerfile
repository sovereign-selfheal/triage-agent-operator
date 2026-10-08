FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --retries 10 --timeout 180 -r requirements.txt

COPY app ./app

RUN useradd -u 1001 -r -g 0 -d /app -s /sbin/nologin appuser && \
    chown -R 1001:0 /app && \
    chmod -R g=u /app
USER 1001

ENV PYTHONUNBUFFERED=1 \
    LOG_LEVEL=INFO

# Cluster-wide watch: the operator reconciles TriageAgent CRs in every namespace. The
# ClusterRole/ClusterRoleBinding for its ServiceAccount is cluster-scoped and lives in
# the `ansible` repo (gitops AGENTS.md section 2), not here.
CMD ["kopf", "run", "--all-namespaces", "-m", "app.operator"]
