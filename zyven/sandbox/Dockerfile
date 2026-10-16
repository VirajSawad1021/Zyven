# Zyven verification sandbox. Dependencies are baked in at build time (with network);
# verification runs later with --network none, non-root, read-only root filesystem.
FROM python:3.12-slim
RUN pip install --no-cache-dir "mcp==2.3.0" "pydantic>=2.7,<3" "pytest>=8,<9" "mpmath>=1.1,<1.4" "hypothesis>=6" \
 && useradd -u 1000 -m zyven
COPY mcp_smoke.py diff_check.py /opt/zyven/
USER 1000
