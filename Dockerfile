# UCAgent Docker Image
# Based on picker base image with verification tools
FROM ghcr.io/xs-mlvp/picker:latest

# The picker base image already provides Node.js, npm, Python 3.11, and pip.
USER root
RUN node --version && \
    npm --version && \
    python3 --version && \
    python3 -m pip --version

# Set working directory
WORKDIR /workspace/ucagent

# Copy project files
COPY requirements.txt pyproject.toml ./
COPY examples/Formal/requirements.txt ./requirements-formal.txt
COPY ucagent/ ./ucagent/
COPY examples/ ./examples/
COPY config.yaml ./
COPY ucagent.py ./
COPY Makefile ./
COPY README.en.md README.zh.md ./
COPY LICENSE ./

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/ucagent

# Install UCAgent and dependencies into the image.
RUN python3 -m pip install . && \
    python3 -m pip install -r requirements-formal.txt && \
    node --version && npm --version && python3 --version && ucagent --check

# Default command: interactive shell
CMD ["/bin/bash"]
