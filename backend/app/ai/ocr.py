"""Reading text from documents: a direct reader for text PDFs (pypdf) and an OCR adapter interface with two optional engines.

`PdfTextReader` needs only pypdf. `TesseractOcr` and `PaddleOcrEngine` import their libraries lazily inside the call; when a library
(or the Tesseract program) is missing they raise ServiceError('ocr_unavailable') that says what to install. Nothing here calls the
network, and nothing here computes an amount: the output is text with positions, to be read by a person or a later extraction step.
"""

import importlib.util
import io
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from app.services.errors import ServiceError

METHODS = ("pdf_text", "tesseract", "paddleocr")
_Q = Decimal("0.0001")


@dataclass(frozen=True)
class PageText:
    page_no: int
    text: str
    method: str
    engine_version: str
    mean_confidence: Decimal | None = None
    blocks: list[dict] | None = None  # [{text, bbox:[x0,y0,x1,y1] as fractions 0..1, confidence}]


class OcrEngine(Protocol):
    method: str

    def read_pages(self, data: bytes, content_type: str) -> list[PageText]: ...


def _unreadable(what: str) -> ServiceError:
    return ServiceError("file_rejected", f"The {what} cannot be read (damaged, password protected or not really that type).")


def _open_pdf(data: bytes) -> Any:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise _unreadable("PDF (it is password protected)")
        len(reader.pages)
        return reader
    except ServiceError:
        raise
    except (PyPdfError, ValueError, OSError, KeyError, TypeError, RecursionError):
        raise _unreadable("PDF") from None


def pdf_page_count(data: bytes) -> int:
    """Number of pages of a PDF; a PDF that cannot be opened is rejected (D-01)."""
    count = len(_open_pdf(data).pages)
    if count < 1:
        raise _unreadable("PDF (it has no pages)")
    return count


class PdfTextReader:
    """Reads the text layer of a PDF directly. A scanned page has no text layer and comes back with empty text."""

    method = "pdf_text"

    def read_pages(self, data: bytes, content_type: str = "application/pdf") -> list[PageText]:
        if content_type != "application/pdf":
            raise ServiceError("invalid_method", "The direct reader works on PDF files only; use an OCR engine for images.")
        import pypdf

        version = f"pypdf-{pypdf.__version__}"
        pages = []
        for number, page in enumerate(_open_pdf(data).pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:  # noqa: BLE001 - pypdf raises many kinds on odd files; the page is treated as having no text layer
                text = ""
            pages.append(PageText(number, text, self.method, version))
        return pages


# ---------------------------------------------------------------------------------------------------- page images (OCR only)


def _have(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _page_images(data: bytes, content_type: str) -> list[Any]:
    """PIL images, one per page. Images need Pillow; PDFs also need pypdfium2."""
    if not _have("PIL"):
        raise ServiceError("ocr_unavailable", "Reading images needs Pillow. Install it with: pip install Pillow")
    from PIL import Image, ImageSequence

    if content_type == "application/pdf":
        if not _have("pypdfium2"):
            raise ServiceError("ocr_unavailable", "OCR of a scanned PDF needs pypdfium2 to draw its pages. Install it with: pip install pypdfium2")
        import pypdfium2

        pdf = pypdfium2.PdfDocument(data)
        return [pdf[i].render(scale=2.5).to_pil().convert("RGB") for i in range(len(pdf))]
    try:
        with Image.open(io.BytesIO(data)) as image:
            return [frame.convert("RGB").copy() for frame in ImageSequence.Iterator(image)]
    except OSError:
        raise _unreadable("image") from None


def _fraction(value: float, size: int) -> float:
    return round(min(max(value / size, 0.0), 1.0), 4) if size else 0.0


class TesseractOcr:
    method = "tesseract"

    def _modules(self) -> Any:
        if not _have("pytesseract"):
            raise ServiceError("ocr_unavailable", "Tesseract OCR is not installed. Install the Tesseract program "
                               "(https://github.com/UB-Mannheim/tesseract/wiki) and then: pip install pytesseract Pillow pypdfium2")
        import pytesseract

        try:
            version = str(pytesseract.get_tesseract_version())
        except Exception:  # noqa: BLE001 - a missing program raises pytesseract.TesseractNotFoundError
            raise ServiceError("ocr_unavailable", "The Python package pytesseract is installed but the Tesseract program was not found. "
                               "Install Tesseract (https://github.com/UB-Mannheim/tesseract/wiki) and add it to PATH.") from None
        return pytesseract, version

    def read_pages(self, data: bytes, content_type: str) -> list[PageText]:
        pytesseract, version = self._modules()
        out = []
        for number, image in enumerate(_page_images(data, content_type), start=1):
            width, height = image.size
            info = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            confs, blocks = [], []
            for i, word in enumerate(info["text"]):
                conf = float(info["conf"][i])
                if not word.strip() or conf < 0:
                    continue
                confidence = Decimal(str(conf / 100)).quantize(_Q)
                confs.append(confidence)
                x, y, w, h = info["left"][i], info["top"][i], info["width"][i], info["height"][i]
                blocks.append({"text": word, "bbox": [_fraction(x, width), _fraction(y, height), _fraction(x + w, width), _fraction(y + h, height)],
                               "confidence": str(confidence)})
            mean = (sum(confs) / len(confs)).quantize(_Q) if confs else None
            out.append(PageText(number, pytesseract.image_to_string(image).strip(), self.method, f"tesseract-{version}", mean, blocks))
        return out


class PaddleOcrEngine:
    method = "paddleocr"

    def read_pages(self, data: bytes, content_type: str) -> list[PageText]:
        if not _have("paddleocr"):
            raise ServiceError("ocr_unavailable", "PaddleOCR is not installed. Install it with: pip install paddleocr paddlepaddle pypdfium2 Pillow")
        import numpy
        import paddleocr

        engine = paddleocr.PaddleOCR(lang="en")
        out = []
        for number, image in enumerate(_page_images(data, content_type), start=1):
            width, height = image.size
            lines = _paddle_lines(engine, numpy.array(image))
            blocks = []
            for text, conf, box in lines:
                xs, ys = [p[0] for p in box], [p[1] for p in box]
                blocks.append({"text": text, "bbox": [_fraction(min(xs), width), _fraction(min(ys), height), _fraction(max(xs), width), _fraction(max(ys), height)],
                               "confidence": str(Decimal(str(conf)).quantize(_Q))})
            confs = [Decimal(b["confidence"]) for b in blocks]
            mean = (sum(confs) / len(confs)).quantize(_Q) if confs else None
            out.append(PageText(number, "\n".join(t for t, _, _ in lines), self.method, f"paddleocr-{paddleocr.__version__}", mean, blocks))
        return out


def _paddle_lines(engine: Any, array: Any) -> list[tuple[str, float, list]]:
    """(text, confidence, box points) per line; copes with the 2.x list result and the 3.x dict result."""
    if hasattr(engine, "predict"):
        lines = []
        for res in engine.predict(array):
            for text, score, poly in zip(res["rec_texts"], res["rec_scores"], res["rec_polys"], strict=False):
                lines.append((str(text), float(score), [tuple(p) for p in poly]))
        return lines
    result = engine.ocr(array, cls=True) or [[]]
    return [(item[1][0], float(item[1][1]), [tuple(p) for p in item[0]]) for item in (result[0] or [])]


_FACTORIES: dict[str, Callable[[], Any]] = {"tesseract": TesseractOcr, "paddleocr": PaddleOcrEngine}


def ocr_for(method: str) -> OcrEngine:
    """The OCR engine for 'tesseract' or 'paddleocr'. Whether its libraries are installed is checked when it reads."""
    if method not in _FACTORIES:
        raise ServiceError("invalid_method", f"Unknown OCR method '{method}'. Use pdf_text, tesseract or paddleocr.")
    return _FACTORIES[method]()


def available_ocr() -> list[str]:
    """OCR engines that look usable on this machine (a library check only; used to pick one for method=auto)."""
    found = []
    if _have("pytesseract") and _have("PIL") and shutil.which("tesseract"):
        found.append("tesseract")
    if _have("paddleocr") and _have("PIL"):
        found.append("paddleocr")
    return found
