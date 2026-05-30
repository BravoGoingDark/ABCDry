FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip and install project requirements (may include non-PyTorch deps)
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt || true

# Install CPU-only PyTorch wheels (recommended for CI/dev without GPU)
# For GPU/CUDA builds, change index-url to the appropriate CUDA wheel index from pytorch.org
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Copy project
COPY . /app

CMD ["/bin/bash"]
