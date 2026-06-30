# UCAgent Docker Image
# Based on picker base image with verification tools
FROM ghcr.io/xs-mlvp/picker:latest

ARG UCAGENT_VERSION

# The picker base image already provides Node.js, npm, Python 3.11, and pip.
USER root
RUN node --version && \
    npm --version && \
    python3 --version && \
    python3 -m pip --version

# Install Code Agent CLIs.
RUN npm install -g @anthropic-ai/claude-code @openai/codex @kilocode/cli opencode-ai && \
    claude --version && \
    kilo --version && \
    opencode --version && \
    codex --version

# Set working directory
WORKDIR /workspace/UCAgent

# Copy project files
COPY . .
COPY examples/Formal/requirements.txt ./requirements-formal.txt

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/UCAgent

# Install UCAgent and dependencies into the image.
RUN : "${UCAGENT_VERSION:?Pass --build-arg UCAGENT_VERSION=<version> when building the image}" && \
    rm -f ucagent/_version.py && \
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_UCAGENT="${UCAGENT_VERSION}" python3 -m pip install . && \
    UCAGENT_VERSION="${UCAGENT_VERSION}" python3 -c "import os; from ucagent.version import __version__; expected = os.environ['UCAGENT_VERSION']; assert __version__ == expected, (__version__, expected)" && \
    python3 -m pip install -r requirements-formal.txt && \
    node --version && npm --version && python3 --version && ucagent --check

# Default command: interactive shell
CMD ["/bin/bash"]
