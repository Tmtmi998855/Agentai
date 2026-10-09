from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["UI Review"])

_UI_REVIEW_HTML_PATH = (
    Path(__file__).resolve().parent.parent.parent / "docs" / "ui-review" / "review.html"
).resolve()


@router.get("/ui-review", response_class=FileResponse)
async def get_ui_review():
    """docs/ui-review/review.html을 text/html로 반환하는 동일 출처 엔드포인트."""
    return FileResponse(_UI_REVIEW_HTML_PATH, media_type="text/html")
