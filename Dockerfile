# UCAgent Docker Image
# Based on picker base image with verification tools
FROM ghcr.io/xs-mlvp/picker:latest

# Install Node.js, npm, and Python 3.11
USER root
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get update && apt-get install -y nodejs python3.11 python3.11-dev python3.11-venv && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/pip3 pip3 /usr/local/bin/pip3.11 1 && \
    rm -rf /var/lib/apt/lists/* && \
    npm install -g npm@latest

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

# Change ownership to user so setuptools-scm can write _version.py
# Also create output dir to avoid permission issues with mounted volumes
RUN chown -R user:user /workspace/ucagent && \
    mkdir -p /workspace/ucagent/output && \
    chown user:user /workspace/ucagent/output

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/ucagent \
    PATH=/home/user/.local/bin:$PATH

# Switch to user for installation
USER user
WORKDIR /workspace/ucagent

# Install UCAgent and dependencies as user with --user flag
RUN pip3 install --user --no-cache-dir . && \
    pip3 install --user --no-cache-dir -r requirements-formal.txt && \
    node --version && npm --version && python3 --version

# Default command: interactive shell
CMD ["/bin/bash"]
