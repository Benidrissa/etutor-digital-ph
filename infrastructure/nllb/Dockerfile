FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Build args pin which pruned + CT2 int8 artifact this image ships. The
# artifact is produced by the Benidrissa/sira-nllb-distill pipeline and
# attached to a GitHub release as ct2_int8.tar.gz. Production overrides
# the tag via docker-compose build.args when cutting a new release.
ARG NLLB_ARTIFACT_RELEASE_REPO=Benidrissa/sira-nllb-distill
ARG NLLB_ARTIFACT_RELEASE_TAG=v1.0.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pull the pinned artifact from a GitHub release and bake it into the image
# so the container starts without any network fetch. The release repo is
# private, which requires the two-step GitHub API pattern:
#   1. GET  /repos/{repo}/releases/tags/{tag}    → find asset by name
#   2. GET  /repos/{repo}/releases/assets/{id}   → with Accept: application/octet-stream
# The browser-style /releases/download/{tag}/{name} URL returns 404 for
# private repos regardless of how the token is passed.
#
# Build needs a GitHub token passed as a build secret:
#   docker build --secret id=gh_token,env=GH_TOKEN .
# In CI this is typically ${{ secrets.GITHUB_TOKEN }} (read-only, scoped to
# the repo) or a PAT with `repo` scope for cross-repo reads.
RUN --mount=type=secret,id=gh_token,required=true \
    GH_TOKEN=$(cat /run/secrets/gh_token) \
    NLLB_REPO="${NLLB_ARTIFACT_RELEASE_REPO}" \
    NLLB_TAG="${NLLB_ARTIFACT_RELEASE_TAG}" \
    python <<'PY'
import json, os, shutil, tarfile, time, urllib.request
token = os.environ["GH_TOKEN"]
repo = os.environ["NLLB_REPO"]
tag = os.environ["NLLB_TAG"]
# Step 1: resolve asset id from tag + filename.
req = urllib.request.Request(
    f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
)
release = json.loads(urllib.request.urlopen(req).read())
asset = next(a for a in release["assets"] if a["name"] == "ct2_int8.tar.gz")
# Step 2: download the asset binary with retries — release-assets CDN can
# drop long streaming connections mid-transfer; a plain retry is usually enough.
last_err = None
for attempt in range(1, 6):
    try:
        req = urllib.request.Request(
            asset["url"],
            headers={"Authorization": f"Bearer {token}", "Accept": "application/octet-stream"},
        )
        with urllib.request.urlopen(req) as src, open("/tmp/nllb-ct2.tar.gz", "wb") as dst:
            shutil.copyfileobj(src, dst)
        if os.path.getsize("/tmp/nllb-ct2.tar.gz") == asset["size"]:
            break
        raise OSError(f"incomplete download on attempt {attempt}")
    except Exception as err:
        last_err = err
        print(f"attempt {attempt}/5 failed: {err}; retrying after {2**attempt}s")
        time.sleep(2 ** attempt)
else:
    raise RuntimeError(f"failed to download {asset['name']} after 5 attempts: {last_err}")
# Extract and move into /models/nllb-ct2/.
with tarfile.open("/tmp/nllb-ct2.tar.gz") as tf:
    tf.extractall("/tmp", filter="data")
os.makedirs("/models/nllb-ct2", exist_ok=True)
for name in os.listdir("/tmp/ct2_int8"):
    shutil.move(f"/tmp/ct2_int8/{name}", f"/models/nllb-ct2/{name}")
os.rmdir("/tmp/ct2_int8")
os.remove("/tmp/nllb-ct2.tar.gz")
print(f"installed artifact from {repo}@{tag} ({asset['size']} bytes)")
PY

COPY server.py .

EXPOSE 5060

# CT2 int8 artifact loads from disk in seconds, not minutes — drop start_period
# from 180s (old transformers+HF download path) to 60s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:5060/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "5060", "--workers", "1"]
