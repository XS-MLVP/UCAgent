# UCAgent Docker Image
# Based on picker base image with verification tools
FROM ghcr.io/xs-mlvp/picker:latest

# Install Node.js and npm
USER root
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/* && \
    npm install -g npm@latest

# Set working directory
WORKDIR /workspace/ucagent

# Copy project files
COPY requirements.txt pyproject.toml ./
COPY ucagent/ ./ucagent/
COPY examples/ ./examples/
COPY config.yaml ./
COPY ucagent.py ./
COPY README.en.md README.zh.md ./

# Install UCAgent and dependencies
RUN pip3 install --no-cache-dir -r requirements.txt && \
    pip3 install --no-cache-dir -e .

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/ucagent:$PYTHONPATH

# Switch back to user for security
USER user
WORKDIR /workspace/ucagent

# Verify installations
RUN node --version && npm --version && python3 --version && ucagent --version || true

# Default command: interactive shell
CMD ["/bin/bash"]
