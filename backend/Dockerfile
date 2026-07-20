FROM python:3.12-slim

# ffmpeg: audio decoding for transcription/diarization
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch first so pyannote.audio doesn't drag in the multi-GB CUDA wheels.
# torchcodec too: the default PyPI wheel links against CUDA 13 (libnvrtc.so.13)
# which isn't in this image — the CPU build decodes fine for pyannote.
RUN pip install --no-cache-dir torch torchaudio torchcodec --index-url https://download.pytorch.org/whl/cpu

# CUDA runtime libs for faster-whisper (CTranslate2 needs cuBLAS + cuDNN 9);
# pip wheels keep the image on python:slim instead of an nvidia/cuda base
RUN pip install --no-cache-dir nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Config is injected at runtime via docker-compose env_file (the single root
# .env), not baked into the image.

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
