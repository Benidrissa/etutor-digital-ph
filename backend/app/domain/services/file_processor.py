"""File processing service for tutor file uploads.

Handles:
- Image files: base64 encoding for Claude vision API
- PDF files: text extraction via PyMuPDF (max 5000 tokens)
- CSV/XLSX files: summary stats + first N rows via basic parsing
- TXT/DOCX: plain text extraction
"""

import base64
import csv
import io
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pymupdf
import structlog

from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()

DANGEROUS_MAGIC_BYTES: list[tuple[bytes, str]] = [
    (b"MZ", "pe_executable"),
    (b"\x7fELF", "elf_executable"),
    (b"#!/", "shell_script"),
    (b"#!", "shell_script"),
]

IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
PDF_MIME_TYPE = "application/pdf"
CSV_MIME_TYPE = "text/csv"
XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TXT_MIME_TYPE = "text/plain"
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass
class ProcessedFile:
    """Result of processing an uploaded file."""

    file_id: str
    original_name: str
    mime_type: str
    size_bytes: int
    file_path: str
    processed_at: datetime
    expires_at: datetime
    content_for_claude: list[dict]


def _check_magic_bytes(data: bytes) -> None:
    """Raise ValueError if file starts with known dangerous magic bytes."""
    for magic, label in DANGEROUS_MAGIC_BYTES:
        if data.startswith(magic):
            raise ValueError(f"Rejected file type: {label}")


def _extract_pdf_text(data: bytes, max_tokens: int) -> str:
    """Extract text from a PDF using PyMuPDF, respecting token budget."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    texts: list[str] = []
    char_budget = max_tokens * 4

    try:
        for page in doc:
            page_text = page.get_text().strip()
            if page_text:
                texts.append(page_text)
                if sum(len(t) for t in texts) >= char_budget:
                    break
    finally:
        doc.close()

    combined = "\n\n".join(texts)
    return combined[:char_budget]


def _parse_csv_text(data: bytes, max_rows: int) -> str:
    """Parse CSV data and return a human-readable summary."""
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows: list[list[str]] = []
    for i, row in enumerate(reader):
        if i > max_rows + 1:
            break
        rows.append(row)

    if not rows:
        return "Empty CSV file."

    header = rows[0] if rows else []
    data_rows = rows[1 : max_rows + 1]
    num_cols = len(header)
    num_rows_total = len(rows) - 1

    lines = [
        f"CSV file — {num_rows_total} rows, {num_cols} columns",
        f"Columns: {', '.join(header)}",
        "",
        "First rows (sample):",
    ]
    for row in data_rows:
        lines.append("  | ".join(str(v) for v in row))

    return "\n".join(lines)


def _extract_docx_text(data: bytes) -> str:
    """Extract plain text from a DOCX file (basic XML parsing)."""
    import xml.etree.ElementTree as ET
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if "word/document.xml" not in z.namelist():
                return "Could not extract text from DOCX."
            xml_content = z.read("word/document.xml")
        root = ET.fromstring(xml_content)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = root.findall(".//w:p", ns)
        texts = []
        for para in paragraphs:
            runs = para.findall(".//w:t", ns)
            para_text = "".join(r.text or "" for r in runs).strip()
            if para_text:
                texts.append(para_text)
        return "\n".join(texts)
    except Exception as e:
        logger.warning("DOCX extraction failed", error=str(e))
        return "Could not extract text from DOCX."


class FileProcessor:
    """Processes uploaded files and prepares content blocks for Claude API."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def prepare_temp_dir(self) -> Path:
        """Ensure temp upload directory exists."""
        temp_dir = Path(self.settings.upload_temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def validate_file(self, filename: str, mime_type: str, size_bytes: int, data: bytes) -> None:
        """Validate file before processing. Raises ValueError on rejection."""
        allowed = self.settings.upload_allowed_types_list
        if mime_type not in allowed:
            raise ValueError(f"File type '{mime_type}' is not allowed.")

        if size_bytes > self.settings.upload_max_size_bytes:
            max_mb = self.settings.upload_max_size_bytes // (1024 * 1024)
            raise ValueError(f"File exceeds maximum size of {max_mb}MB.")

        _check_magic_bytes(data)

        ext = Path(filename).suffix.lower()
        dangerous_extensions = {".exe", ".sh", ".bat", ".py", ".js", ".cmd", ".ps1", ".dll"}
        if ext in dangerous_extensions:
            raise ValueError(f"File extension '{ext}' is not allowed.")

    async def process(
        self, filename: str, mime_type: str, data: bytes, user_id: uuid.UUID
    ) -> ProcessedFile:
        """Process an uploaded file: validate, store, prepare Claude content blocks."""
        size_bytes = len(data)
        self.validate_file(filename, mime_type, size_bytes, data)

        temp_dir = self.prepare_temp_dir()
        file_id = str(uuid.uuid4())
        safe_ext = Path(filename).suffix.lower() or ".bin"
        file_path = temp_dir / f"{user_id}_{file_id}{safe_ext}"
        file_path.write_bytes(data)

        now = datetime.utcnow()
        expires_at = now + timedelta(hours=self.settings.upload_ttl_hours)

        content_blocks = self._build_content_blocks(mime_type, data)

        logger.info(
            "File processed",
            file_id=file_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            user_id=str(user_id),
        )

        return ProcessedFile(
            file_id=file_id,
            original_name=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            file_path=str(file_path),
            processed_at=now,
            expires_at=expires_at,
            content_for_claude=content_blocks,
        )

    def _build_content_blocks(self, mime_type: str, data: bytes) -> list[dict]:
        """Build Claude API content blocks from raw file data."""
        if mime_type in IMAGE_MIME_TYPES:
            return self._image_blocks(mime_type, data)
        elif mime_type == PDF_MIME_TYPE:
            return self._pdf_blocks(data)
        elif mime_type in {CSV_MIME_TYPE, XLSX_MIME_TYPE}:
            return self._csv_blocks(mime_type, data)
        elif mime_type == DOCX_MIME_TYPE:
            return self._docx_blocks(data)
        else:
            return self._text_blocks(data)

    def _image_blocks(self, mime_type: str, data: bytes) -> list[dict]:
        b64 = base64.standard_b64encode(data).decode("ascii")
        media_map = {
            "image/jpg": "image/jpeg",
            "image/jpeg": "image/jpeg",
            "image/png": "image/png",
            "image/webp": "image/webp",
            "image/gif": "image/gif",
        }
        media_type = media_map.get(mime_type, "image/jpeg")
        return [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            }
        ]

    def _pdf_blocks(self, data: bytes) -> list[dict]:
        text = _extract_pdf_text(data, self.settings.upload_max_pdf_tokens)
        if not text.strip():
            text = "(PDF contained no extractable text)"
        return [{"type": "text", "text": f"[PDF content]\n{text}"}]

    def _csv_blocks(self, mime_type: str, data: bytes) -> list[dict]:
        if mime_type == XLSX_MIME_TYPE:
            summary = self._parse_xlsx(data)
        else:
            summary = _parse_csv_text(data, self.settings.upload_max_csv_rows)
        return [{"type": "text", "text": f"[Spreadsheet content]\n{summary}"}]

    def _parse_xlsx(self, data: bytes) -> str:
        """Parse XLSX using zipfile + basic XML (no pandas dependency required)."""
        import xml.etree.ElementTree as ET
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = z.namelist()
                sheet_path = next(
                    (
                        n
                        for n in names
                        if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
                    ),
                    None,
                )
                if not sheet_path:
                    return "Could not read XLSX sheet."

                shared_strings: list[str] = []
                if "xl/sharedStrings.xml" in names:
                    ss_xml = z.read("xl/sharedStrings.xml")
                    ss_root = ET.fromstring(ss_xml)
                    ns = {"ns": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    for si in ss_root.findall("ns:si", ns):
                        t_elements = si.findall(".//ns:t", ns)
                        shared_strings.append("".join(t.text or "" for t in t_elements))

                sheet_xml = z.read(sheet_path)
                sheet_root = ET.fromstring(sheet_xml)
                ns2 = {"ns": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                rows = sheet_root.findall(".//ns:row", ns2)
                result_rows: list[list[str]] = []
                for row in rows[: self.settings.upload_max_csv_rows + 1]:
                    cells = row.findall("ns:c", ns2)
                    row_vals: list[str] = []
                    for cell in cells:
                        t_attr = cell.get("t", "")
                        v_el = cell.find("ns:v", ns2)
                        val = v_el.text if v_el is not None else ""
                        if t_attr == "s" and val is not None:
                            idx = int(val)
                            val = shared_strings[idx] if idx < len(shared_strings) else val
                        row_vals.append(val or "")
                    result_rows.append(row_vals)

            if not result_rows:
                return "Empty spreadsheet."

            header = result_rows[0]
            data_rows = result_rows[1:]
            lines = [
                f"XLSX file — {len(data_rows)} rows, {len(header)} columns",
                f"Columns: {', '.join(header)}",
                "",
                "First rows (sample):",
            ]
            for row in data_rows[: self.settings.upload_max_csv_rows]:
                lines.append("  | ".join(row))
            return "\n".join(lines)
        except Exception as e:
            logger.warning("XLSX parse failed", error=str(e))
            return "Could not parse XLSX file."

    def _docx_blocks(self, data: bytes) -> list[dict]:
        text = _extract_docx_text(data)
        max_chars = self.settings.upload_max_pdf_tokens * 4
        return [{"type": "text", "text": f"[Document content]\n{text[:max_chars]}"}]

    def _text_blocks(self, data: bytes) -> list[dict]:
        text = data.decode("utf-8", errors="replace")
        max_chars = self.settings.upload_max_pdf_tokens * 4
        return [{"type": "text", "text": f"[Text file content]\n{text[:max_chars]}"}]

    def load_content_blocks_from_path(self, file_path: str, mime_type: str) -> list[dict]:
        """Reload content blocks from a stored temp file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Temp file not found: {file_path}")
        data = path.read_bytes()
        return self._build_content_blocks(mime_type, data)

    def cleanup_expired_files(self) -> int:
        """Delete temp files older than the TTL. Returns count deleted."""
        temp_dir = Path(self.settings.upload_temp_dir)
        if not temp_dir.exists():
            return 0

        cutoff = datetime.utcnow() - timedelta(hours=self.settings.upload_ttl_hours)
        deleted = 0
        for f in temp_dir.iterdir():
            if f.is_file():
                mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    try:
                        f.unlink()
                        deleted += 1
                    except Exception as e:
                        logger.warning("Failed to delete expired upload", path=str(f), error=str(e))

        logger.info("Cleaned up expired uploads", deleted=deleted)
        return deleted
