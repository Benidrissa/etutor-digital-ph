"""Meta MMS TTS HTTP server for Moore, Dioula, and Bambara.

Preloads Hugging Face `facebook/mms-tts-{mos,dyu,bam}` VITS models on startup and
serves synthesized speech as OGG/Opus over HTTP. Opus at ~24 kbps keeps a
30-second clip under ~100 KB, which matters for 2G/3G West African networks.
"""
from __future__ import annotations

import io
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Literal

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from pydub import AudioSegment
from scipy.io import wavfile
from transformers import AutoTokenizer, VitsModel

SUPPORTED_LANGUAGES = ("mos", "dyu", "bam")
Language = Literal["mos", "dyu", "bam"]

MAX_TEXT_CHARS = 2000
OPUS_BITRATE = "24k"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("mms-tts")


class _ModelBundle:
    __slots__ = ("model", "tokenizer", "sample_rate")

    def __init__(self, model: VitsModel, tokenizer: AutoTokenizer, sample_rate: int):
        self.model = model
        self.tokenizer = tokenizer
        self.sample_rate = sample_rate


_MODELS: dict[str, _ModelBundle] = {}


def _load_model(lang: str) -> _ModelBundle:
    model_id = f"facebook/mms-tts-{lang}"
    logger.info("loading %s", model_id)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = VitsModel.from_pretrained(model_id)
    model.eval()
    return _ModelBundle(model=model, tokenizer=tokenizer, sample_rate=model.config.sampling_rate)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    langs = [l for l in os.getenv("MMS_LANGUAGES", ",".join(SUPPORTED_LANGUAGES)).split(",") if l]
    for lang in langs:
        if lang not in SUPPORTED_LANGUAGES:
            logger.warning("skipping unsupported language: %s", lang)
            continue
        _MODELS[lang] = _load_model(lang)
    logger.info("loaded models: %s", list(_MODELS.keys()))
    yield
    _MODELS.clear()


app = FastAPI(title="MMS TTS Sidecar", version="1.0.0", lifespan=lifespan)


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_CHARS)
    language: Language


def _synthesize_wav(text: str, bundle: _ModelBundle) -> tuple[int, np.ndarray]:
    inputs = bundle.tokenizer(text, return_tensors="pt")
    with torch.no_grad():
        output = bundle.model(**inputs).waveform
    waveform = output.squeeze().cpu().numpy()
    waveform = np.clip(waveform, -1.0, 1.0)
    pcm16 = (waveform * 32767).astype(np.int16)
    return bundle.sample_rate, pcm16


def _wav_to_opus(sample_rate: int, pcm16: np.ndarray) -> bytes:
    wav_buf = io.BytesIO()
    wavfile.write(wav_buf, sample_rate, pcm16)
    wav_buf.seek(0)

    audio = AudioSegment.from_file(wav_buf, format="wav")
    opus_buf = io.BytesIO()
    audio.export(
        opus_buf,
        format="ogg",
        codec="libopus",
        bitrate=OPUS_BITRATE,
        parameters=["-application", "voip"],
    )
    return opus_buf.getvalue()


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "languages": list(_MODELS.keys())})


@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest) -> Response:
    bundle = _MODELS.get(req.language)
    if bundle is None:
        raise HTTPException(status_code=400, detail=f"language not loaded: {req.language}")

    started = time.monotonic()
    try:
        sample_rate, pcm16 = _synthesize_wav(req.text, bundle)
        opus_bytes = _wav_to_opus(sample_rate, pcm16)
    except Exception as exc:
        logger.exception("synthesis failed for %s: %s", req.language, exc)
        raise HTTPException(status_code=500, detail="synthesis failed") from exc

    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "synth lang=%s chars=%d bytes=%d elapsed_ms=%d",
        req.language,
        len(req.text),
        len(opus_bytes),
        elapsed_ms,
    )
    return Response(
        content=opus_bytes,
        media_type="audio/ogg",
        headers={
            "X-Audio-Codec": "opus",
            "X-Audio-Sample-Rate": str(sample_rate),
            "X-Synth-Elapsed-Ms": str(elapsed_ms),
        },
    )
