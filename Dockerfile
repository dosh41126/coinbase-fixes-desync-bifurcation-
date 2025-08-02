FROM python:3.11-slim-bookworm

ENV PIP_NO_CACHE_DIR=1 \
    CMAKE_ARGS="-DLLAMA_BLAS=ON -DLLAMA_BLAS_VENDOR=OpenBLAS" \
    LLAMA_MODEL_PATH="/models/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf" \
    LLAMA_CTX="4096" \
    LLAMA_TEMPERATURE="0.2" \
    LLAMA_TOP_P="0.95" \
    LLAMA_MAX_TOKENS="256" \
    LLAMA_N_GPU_LAYERS="-1" \
    OMP_NUM_THREADS="4" \
    OPENBLAS_NUM_THREADS="4" \
    MKL_NUM_THREADS="4"

# Minimal system dependencies for llama-cpp-python with OpenBLAS
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      cmake \
      libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install "llama-cpp-python>=0.2.90"

# Copy agent code
COPY coinbase_llama_desync_agent_adv.py ./coinbase_llama_desync_agent_adv.py

# Default command (model must exist at $LLAMA_MODEL_PATH)
CMD ["python", "coinbase_llama_desync_agent_adv.py"]
