"""Meta NLLB-200-distilled-600M translation server (#1694).

Shared multi-tenant inference service. Loads Meta's
``facebook/nllb-200-distilled-600M`` once (~2.4 GB RAM) and serves
translations over HTTP — every tenant points at this same container
instead of running its own 2.4 GB copy.

Target language pairs for driving-school QBank v1: French source →
``{fra_Latn, mos_Latn, dyu_Latn, bam_Latn}`` targets. The model supports
200 languages; we don't restrict the endpoint, but document that
low-resource language quality (mos/dyu/bam) is notably worse than
fr↔en and callers should review translations before publishing.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

MODEL_ID = os.getenv("NLLB_MODEL_ID", "facebook/nllb-200-distilled-600M")
MAX_TEXT_CHARS = 4000
MAX_NEW_TOKENS = 512

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nllb")


class _Bundle:
    __slots__ = ("model", "tokenizer")

    def __init__(self, model, tokenizer):
        self.model = model
        self.tokenizer = tokenizer


_STATE: dict[str, _Bundle] = {}


def _load() -> _Bundle:
    logger.info("loading %s", MODEL_ID)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_ID)
    model.eval()
    logger.info("loaded %s", MODEL_ID)
    return _Bundle(model=model, tokenizer=tokenizer)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        _STATE["bundle"] = _load()
    except Exception:
        # Don't crash lifespan — /translate will 503 until retry/restart.
        # Matches the resilience pattern in infrastructure/mms-tts/server.py.
        logger.exception("failed to load NLLB model")
    yield
    _STATE.clear()


app = FastAPI(title="NLLB Translation Sidecar", version="1.0.0", lifespan=lifespan)


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_CHARS)
    src_lang: str = Field(..., description="NLLB flores-200 code, e.g. fra_Latn")
    tgt_lang: str = Field(..., description="NLLB flores-200 code, e.g. mos_Latn")


class TranslateResponse(BaseModel):
    translation: str
    src_lang: str
    tgt_lang: str
    elapsed_ms: int


class BatchTranslateRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=64)
    src_lang: str
    tgt_lang: str


class BatchTranslateResponse(BaseModel):
    translations: list[str]
    src_lang: str
    tgt_lang: str
    elapsed_ms: int


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok" if "bundle" in _STATE else "loading", "model": MODEL_ID})


def _translate(texts: list[str], src_lang: str, tgt_lang: str) -> list[str]:
    bundle = _STATE.get("bundle")
    if bundle is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    tokenizer = bundle.tokenizer
    model = bundle.model

    # NLLB requires src_lang on the tokenizer so the BOS token is right.
    # We assign then restore in a try/finally to keep the tokenizer safe
    # under concurrent requests (uvicorn workers=1 but FastAPI still runs
    # handlers concurrently via threadpool).
    prev_src = tokenizer.src_lang
    tokenizer.src_lang = src_lang
    try:
        inputs = tokenizer(texts, return_tensors="pt", padding=True, truncation=True)
        forced_bos = tokenizer.convert_tokens_to_ids(tgt_lang)
        if forced_bos == tokenizer.unk_token_id:
            raise HTTPException(status_code=400, detail=f"unknown tgt_lang: {tgt_lang}")
        with torch.no_grad():
            generated = model.generate(
                **inputs,
                forced_bos_token_id=forced_bos,
                max_new_tokens=MAX_NEW_TOKENS,
                num_beams=1,
            )
        return tokenizer.batch_decode(generated, skip_special_tokens=True)
    finally:
        tokenizer.src_lang = prev_src


@app.post("/translate", response_model=TranslateResponse)
async def translate(req: TranslateRequest) -> TranslateResponse:
    started = time.monotonic()
    out = _translate([req.text], req.src_lang, req.tgt_lang)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "translate src=%s tgt=%s chars=%d elapsed_ms=%d",
        req.src_lang,
        req.tgt_lang,
        len(req.text),
        elapsed_ms,
    )
    return TranslateResponse(
        translation=out[0],
        src_lang=req.src_lang,
        tgt_lang=req.tgt_lang,
        elapsed_ms=elapsed_ms,
    )


@app.post("/translate/batch", response_model=BatchTranslateResponse)
async def translate_batch(req: BatchTranslateRequest) -> BatchTranslateResponse:
    started = time.monotonic()
    out = _translate(req.texts, req.src_lang, req.tgt_lang)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "batch src=%s tgt=%s n=%d elapsed_ms=%d",
        req.src_lang,
        req.tgt_lang,
        len(req.texts),
        elapsed_ms,
    )
    return BatchTranslateResponse(
        translations=out,
        src_lang=req.src_lang,
        tgt_lang=req.tgt_lang,
        elapsed_ms=elapsed_ms,
    )
