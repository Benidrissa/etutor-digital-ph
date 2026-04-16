import io
import logging
import os
from contextlib import asynccontextmanager

import scipy.io.wavfile
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from transformers import VitsModel, AutoTokenizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = {
    "mos": "facebook/mms-tts-mos",
    "dyu": "facebook/mms-tts-dyu",
    "bam": "facebook/mms-tts-bam",
}

models: dict = {}
tokenizers: dict = {}


def load_models() -> None:
    for lang, model_id in SUPPORTED_LANGUAGES.items():
        logger.info(f"Loading model for {lang}: {model_id}")
        try:
            tokenizers[lang] = AutoTokenizer.from_pretrained(model_id)
            models[lang] = VitsModel.from_pretrained(model_id)
            models[lang].eval()
            logger.info(f"Model loaded for {lang}")
        except Exception as e:
            logger.error(f"Failed to load model for {lang}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_models()
    yield


app = FastAPI(title="MMS TTS Server", lifespan=lifespan)


class SynthesizeRequest(BaseModel):
    text: str
    language: str


@app.get("/health")
async def health() -> dict:
    loaded = [lang for lang in SUPPORTED_LANGUAGES if lang in models]
    return {"status": "ok", "loaded_languages": loaded}


@app.post("/synthesize")
async def synthesize(request: SynthesizeRequest) -> Response:
    lang = request.language.lower()
    if lang not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language '{lang}'. Supported: {list(SUPPORTED_LANGUAGES.keys())}",
        )
    if lang not in models:
        raise HTTPException(
            status_code=503,
            detail=f"Model for language '{lang}' is not loaded.",
        )
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text must not be empty.")

    try:
        inputs = tokenizers[lang](request.text, return_tensors="pt")
        with torch.no_grad():
            output = models[lang](**inputs)
        waveform = output.waveform.squeeze().numpy()
        sample_rate = models[lang].config.sampling_rate

        buf = io.BytesIO()
        scipy.io.wavfile.write(buf, sample_rate, waveform)
        buf.seek(0)
        return Response(content=buf.read(), media_type="audio/wav")
    except Exception as e:
        logger.error(f"Synthesis failed for language '{lang}': {e}")
        raise HTTPException(status_code=500, detail="Synthesis failed.")
