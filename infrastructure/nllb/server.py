"""NLLB translation HTTP server — CTranslate2 int8, vocab-pruned artifact.

Translates short driving-school qbank texts from French to four low-resource
West African languages: Mooré (mos_Latn), Dioula (dyu_Latn), Bambara
(bam_Latn), and Fulfulde — Nigerian variant (fuv_Latn). Pairs with the
MMS TTS sidecar: translate here first, synthesize audio there.

Replaces the earlier transformers + torch implementation with a CTranslate2
int8 pipeline (#1709). The artifact is a vocab-pruned fork of
``facebook/nllb-200-distilled-600M`` restricted to {fra, mos, dyu, bam, fuv}
and produced by the Benidrissa/sira-nllb-distill pipeline; see
``infrastructure/nllb/Dockerfile`` for how it's baked into the image.

HTTP contract is preserved bit-for-bit from the transformers era so
``backend/app/integrations/nllb_translate.py`` doesn't change:
    POST /translate  {texts, src, tgt}  ->  {translations, elapsed_ms}
    GET  /health                         ->  {status, model_loaded, ...}

Decoding knobs (beam, no_repeat_ngram, repetition_penalty, max_decoding_length)
match what landed on dev to fix mos/dyu/bam/ful repetition loops (#1706 +
#1712). CT2's Translator.translate_batch() accepts all of them natively.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import ctranslate2
import sentencepiece as spm
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

MODEL_DIR = Path(os.getenv("NLLB_MODEL_DIR", "/models/nllb-ct2"))
SP_MODEL_PATH = MODEL_DIR / "sentencepiece.bpe.model"

MAX_INPUT_CHARS = 2000
MAX_TEXTS_PER_BATCH = 32
# Short qbank content rarely needs more than ~80 output tokens. A high cap
# only slows decoding by running past EOS on CPU.
MAX_NEW_TOKENS = 96

# Decoding parameters — greedy (beam=1) with no_repeat_ngram + repetition
# penalty to prevent degenerate loops on mos/dyu/bam/ful. beam=4 was too
# slow on the old transformers path (#1712), but may be worth revisiting
# on CT2 int8; leave greedy for now to match dev's shipping settings.
BEAM_SIZE = int(os.getenv("NLLB_BEAM_SIZE", "1"))
NO_REPEAT_NGRAM_SIZE = 3
REPETITION_PENALTY = 1.2

COMPUTE_TYPE = os.getenv("NLLB_COMPUTE_TYPE", "int8")
INTER_THREADS = int(os.getenv("NLLB_INTER_THREADS", "1"))
INTRA_THREADS = int(os.getenv("NLLB_INTRA_THREADS", "0"))  # 0 = auto

# Serialize translate_batch() calls — CT2 is thread-safe but concurrent
# Python callers under a single-worker uvicorn still pin the CPU. Keeping
# the same semaphore pattern as the transformers version (#1705) prevents
# a spike of concurrent /translate requests from making /health time out.
_TRANSLATE_SEMAPHORE = asyncio.Semaphore(1)

DEFAULT_SOURCE = "fra_Latn"
SUPPORTED_TARGETS = ("mos_Latn", "dyu_Latn", "bam_Latn", "fuv_Latn")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nllb")


class _Bundle:
    __slots__ = ("translator", "sp")

    def __init__(self, translator: ctranslate2.Translator, sp: spm.SentencePieceProcessor):
        self.translator = translator
        self.sp = sp


_BUNDLE: _Bundle | None = None


def _load() -> _Bundle:
    logger.info("loading CT2 model from %s (compute_type=%s)", MODEL_DIR, COMPUTE_TYPE)
    translator = ctranslate2.Translator(
        str(MODEL_DIR),
        device="cpu",
        compute_type=COMPUTE_TYPE,
        inter_threads=INTER_THREADS,
        intra_threads=INTRA_THREADS,
    )
    sp = spm.SentencePieceProcessor()
    sp.load(str(SP_MODEL_PATH))
    logger.info("loaded CT2 model + SentencePiece (vocab=%d)", sp.get_piece_size())
    return _Bundle(translator=translator, sp=sp)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _BUNDLE
    # Don't crash lifespan on load failure — /health will return 503
    # until the container is restarted. Same resilience pattern as the
    # MMS sidecar (#1681).
    try:
        _BUNDLE = _load()
        logger.info("nllb model loaded")
    except Exception as exc:
        logger.exception("failed to load nllb ct2 model: %s", exc)
        _BUNDLE = None
    yield
    _BUNDLE = None


app = FastAPI(title="NLLB Translation Sidecar (CT2 int8)", version="2.0.0", lifespan=lifespan)


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
            "model_dir": str(MODEL_DIR),
            "compute_type": COMPUTE_TYPE,
            "supported_targets": list(SUPPORTED_TARGETS),
            "default_source": DEFAULT_SOURCE,
        },
        status_code=200 if loaded else 503,
    )


def _encode(sp: spm.SentencePieceProcessor, text: str, src: str) -> list[str]:
    # NLLB source-side format: [src_lang, *sp_pieces, </s>]
    return [src, *sp.encode_as_pieces(text), "</s>"]


def _decode(sp: spm.SentencePieceProcessor, tokens: list[str], tgt: str) -> str:
    # Strip the forced target-language prefix CT2 echoes back.
    if tokens and tokens[0] == tgt:
        tokens = tokens[1:]
    return sp.decode(tokens)


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

    sp = _BUNDLE.sp
    translator = _BUNDLE.translator

    # Validate tgt against the pruned artifact's kept languages. Language
    # codes live in the CT2-extended vocabulary, not the raw SentencePiece
    # model, so probing the SP vocab always returns unk_id — whitelist-check
    # instead. (#1709 hotfix: the SP probe rejected every valid target.)
    if req.tgt not in SUPPORTED_TARGETS:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported target lang {req.tgt}; expected one of {list(SUPPORTED_TARGETS)}",
        )

    async with _TRANSLATE_SEMAPHORE:
        started = time.monotonic()
        batch = [_encode(sp, t, req.src) for t in req.texts]
        target_prefix = [[req.tgt]] * len(batch)
        results = translator.translate_batch(
            batch,
            target_prefix=target_prefix,
            max_decoding_length=MAX_NEW_TOKENS,
            beam_size=BEAM_SIZE,
            no_repeat_ngram_size=NO_REPEAT_NGRAM_SIZE,
            repetition_penalty=REPETITION_PENALTY,
        )
        translations = [_decode(sp, r.hypotheses[0], req.tgt) for r in results]
        elapsed_ms = int((time.monotonic() - started) * 1000)

    logger.info(
        "translate src=%s tgt=%s batch=%d elapsed_ms=%d",
        req.src,
        req.tgt,
        len(req.texts),
        elapsed_ms,
    )
    return TranslateResponse(translations=translations, elapsed_ms=elapsed_ms)
