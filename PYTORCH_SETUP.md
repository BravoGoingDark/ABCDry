PyTorch setup notes
===================

This project uses PyTorch for LSTM forecasting. Below are quick install and Docker instructions.

CPU (recommended for local dev):

```bash
python -m pip install --upgrade pip setuptools wheel
# Install other requirements first (if present)
pip install -r requirements.txt || true
# Then install CPU-only PyTorch wheels
pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

GPU (CUDA):

Visit https://pytorch.org and follow the selector to get the correct `pip` command for your CUDA version. Example for CUDA 12.1:

```bash
pip install --index-url https://download.pytorch.org/whl/cu121 torch torchvision torchaudio --extra-index-url https://pypi.org/simple
```

Docker (build and run):

```bash
# Build image (from repo root)
docker build -t cursoragri:latest .

# Run an interactive shell
docker run --rm -it -v $(pwd):/app cursoragri:latest
```

Notes
- The Dockerfile in the repo installs CPU-only PyTorch by default; edit the Dockerfile if you need a CUDA-enabled image.
- If `requirements.txt` pins a `torch` version, the explicit `pip install` for PyTorch in the Dockerfile will ensure the CPU wheel is installed from the PyTorch index.
