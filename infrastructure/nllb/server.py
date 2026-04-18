"""Meta NLLB-200 translation HTTP server.

Translates short driving-school qbank texts from French to four low-resource
West African languages: Mooré (mos_Latn), Dioula (dyu_Latn), Bambara
(bam_Latn), and Fulfulde — Western Niger variant (fuh_Latn). Pairs with the
MMS TTS sidecar: translate here first, synthesize audio there. MMS is
monolingual TTS and will pronounce French syllables with the target
phonology if fed raw French; this service fixes that (#1690).

Model: ``facebook/nllb-200-distilled-600M`` (~2.4 GB RAM). Preloads the
model once on startup and keeps it hot. Batch translate up to ~10 short
texts in one forward pass.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

MAX_INPUT_CHARS = 2000
MAX_TEXTS_PER_BATCH = 32
MAX_NEW_TOKENS = 256

# NLLB source/target codes for the qbank pipeline. The sidecar itself is
# source-agnostic (NLLB-200 handles 200+ languages); the backend picks
# the right source code per bank and sends it here. These constants are
# only used for the ``/health`` payload and input validation reporting.
DEFAULT_SOURCE = "fra_Latn"
SUPPORTED_TARGETS = ("mos_Latn", "dyu_Latn", "bam_Latn", "fuv_Latn")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nllb")


class _Bundle:
    __slots__ = ("model", "tokenizer")

    def __init__(self, model, tokenizer):
        self.model = model
        self.tokenizer = tokenizer


_BUNDLE: _Bundle | None = None


def _load_model() -> _Bundle:
    model_id = os.getenv("NLLB_MODEL_ID", "facebook/nllb-200-distilled-600M")
    logger.info("loading %s", model_id)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
    model.eval()
    return _Bundle(model=model, tokenizer=tokenizer)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _BUNDLE
    # Per-language loading isn't a concept for NLLB — one model handles
    # all 200+ target codes. If the model itself fails to download we
    # log and keep the server alive so /health reflects the outage
    # without taking the container into a crash loop (same resilience
    # pattern as the MMS sidecar after #1681).
    try:
        _BUNDLE = _load_model()
        logger.info("nllb model loaded")
    except Exception as exc:
        logger.exception("failed to load nllb model: %s", exc)
        _BUNDLE = None
    yield
    _BUNDLE = None


app = FastAPI(title="NLLB Translation Sidecar", version="1.0.0", lifespan=lifespan)


class TranslateRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=MAX_TEXTS_PER_BATCH)
    src: str = Field(default=DEFAULT_SOURCE, min_length=3, max_length=16)
    tgt: str = Field(..., min_length=3, max_length=16)


class TranslateResponse(BaseModel):
    translations: list[str]
    elapsed_ms: int


@app.get("/health")
async def health() -> JSONResponse:
    loaded = _BUNDLE is not None
    return JSONResponse(
        {
            "status": "ok" if loaded else "degraded",
            "model_loaded": loaded,
            "supported_targets": list(SUPPORTED_TARGETS),
            "default_source": DEFAULT_SOURCE,
        },
        status_code=200 if loaded else 503,
    )


@app.post("/translate", response_model=TranslateResponse)
async def translate(req: TranslateRequest) -> TranslateResponse:
    if _BUNDLE is None:
        raise HTTPException(status_code=503, detail="model not loaded")

    for text in req.texts:
        if len(text) > MAX_INPUT_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"input text exceeds {MAX_INPUT_CHARS} characters",
            )

    tokenizer = _BUNDLE.tokenizer
    model = _BUNDLE.model
    tokenizer.src_lang = req.src

    started = time.monotonic()
    inputs = tokenizer(
        req.texts,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=MAX_INPUT_CHARS,
    )

    # NLLB forced_bos_token_id selects the target language at generation
    # time. ``convert_tokens_to_ids`` is the supported way to retrieve it
    # across transformers versions.
    tgt_id = tokenizer.convert_tokens_to_ids(req.tgt)
    if tgt_id is None or tgt_id == tokenizer.unk_token_id:
        raise HTTPException(status_code=400, detail=f"unknown target lang: {req.tgt}")

    generated = model.generate(
        **inputs,
        forced_bos_token_id=tgt_id,
        max_new_tokens=MAX_NEW_TOKENS,
        num_beams=1,
    )
    translations = tokenizer.batch_decode(generated, skip_special_tokens=True)
    elapsed_ms = int((time.monotonic() - started) * 1000)

    logger.info(
        "translate src=%s tgt=%s batch=%d elapsed_ms=%d",
        req.src,
        req.tgt,
        len(req.texts),
        elapsed_ms,
    )
    return TranslateResponse(translations=translations, elapsed_ms=elapsed_ms)
