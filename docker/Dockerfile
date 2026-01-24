# Minimal sandbox image for executing Python solutions and tests
FROM python:3.12-slim

# Create non-root user for safety
RUN useradd -ms /bin/bash sandbox

WORKDIR /workspace

# Do not install extra packages by default; keep environment minimal
# Optionally, you can pre-install pytest if needed per task (uncomment):
# RUN pip install --no-cache-dir pytest

USER sandbox

CMD ["python", "-V"]

