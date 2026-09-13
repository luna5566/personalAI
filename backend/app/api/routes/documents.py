import logging
from typing import Annotated
from urllib.parse import quote as url_quote
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.api.deps import authenticated_user_id, db_session
from app.core.config import settings
from app.core.pagination import (
    CURSOR_MAX_LENGTH,
    MAX_PAGE_NUMBER,
    decode_timestamp_id_cursor,
    encode_timestamp_id_cursor,
)
from app.core.request_limits import (
    DOCUMENT_DETAIL_CONTENT_OFFSET_MAX,
    DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH,
    DOCUMENT_SEARCH_KEYWORD_MAX_LENGTH,
    DOCUMENT_TITLE_MAX_LENGTH,
    TAG_NAME_MAX_LENGTH,
    UPLOAD_TAGS_FORM_MAX_LENGTH,
)
from app.models.document import DocumentSourceType, DocumentStatus
from app.models.job import JobType
from app.schemas.document import (
    DocumentListResponse,
    DocumentRead,
    DocumentScanResponse,
    DocumentStatsRead,
    DocumentUpdate,
    DocumentUploadResponse,
    NoteCreate,
    RelatedDocumentRead,
)
from app.services import document_service, job_service, tag_service
from app.storage import storage_service
from app.workers.document_pipeline import process_document
from app.workers.job_execution import run_job_with_worker_limit
from app.workers.storage_deletion import StorageDeletionWakeup

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)
DOCUMENT_SCAN_CURSOR_KIND = "documents.created-id.desc"


@router.post("/note", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def create_note(
    payload: NoteCreate,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> DocumentRead:
    document = document_service.create_note(db, user_id, payload)
    return document_service.to_document_detail_view(document)


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
    file: UploadFile = File(...),
    title: Annotated[
        str | None,
        Form(max_length=DOCUMENT_TITLE_MAX_LENGTH),
    ] = None,
    source_type: Annotated[DocumentSourceType | None, Form()] = None,
    tags: Annotated[
        str | None,
        Form(max_length=UPLOAD_TAGS_FORM_MAX_LENGTH),
    ] = None,
) -> DocumentUploadResponse:
    original_filename = file.filename or "unknown"
    parsed_tags = _parse_tags(tags)
    try:
        document_service.validate_file_document_metadata(
            original_filename=original_filename,
            mime_type=file.content_type,
        )
    except document_service.FileDocumentMetadataValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    detected_source_type = source_type or _detect_source_type(file.filename or "", file.content_type)
    _reject_unavailable_media_upload(detected_source_type)
    try:
        storage_key, file_size = await storage_service.save_upload(
            file,
            original_filename=file.filename,
            max_size_bytes=settings.max_upload_size_bytes,
        )
    except storage_service.UploadTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc

    if file_size == 0:
        storage_service.delete_key(storage_key)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    try:
        document = document_service.add_file_document(
            db=db,
            user_id=user_id,
            title=(title.strip() if title and title.strip() else _title_from_filename(file.filename or "未命名资料")),
            source_type=detected_source_type,
            file_path=storage_key,
            original_filename=original_filename,
            file_size=file_size,
            mime_type=file.content_type,
            tags=parsed_tags,
        )
        job = job_service.add_job(
            db,
            user_id,
            document.id,
            JobType.INDEX_DOCUMENT,
        )
    except Exception:
        _rollback_upload_transaction(db)
        try:
            storage_service.delete_key(storage_key)
        except Exception:
            logger.warning(
                "Failed to remove an uncommitted upload",
                exc_info=True,
            )
        raise
    try:
        db.commit()
    except Exception:
        _rollback_upload_transaction(db)
        logger.warning(
            "Upload database commit failed; retaining the file because commit outcome may be unknown",
            exc_info=True,
        )
        raise

    db.refresh(document)
    db.refresh(job)
    background_tasks.add_task(
        run_job_with_worker_limit,
        process_document,
        job.id,
        document.id,
    )

    return DocumentUploadResponse(
        document_id=document.id,
        job_id=job.id,
        filename=document.original_filename or "unknown",
        status=DocumentStatus.UPLOADED,
    )


@router.get("", response_model=DocumentListResponse)
def list_documents(
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE_NUMBER)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[
        str | None,
        Query(max_length=DOCUMENT_SEARCH_KEYWORD_MAX_LENGTH),
    ] = None,
    source_type: DocumentSourceType | None = None,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    tag: Annotated[str | None, Query(max_length=TAG_NAME_MAX_LENGTH)] = None,
) -> DocumentListResponse:
    items, total = document_service.list_documents(
        db=db,
        user_id=user_id,
        page=page,
        page_size=page_size,
        keyword=keyword,
        source_type=source_type,
        status=status_filter,
        tag=tag,
    )
    document_service.attach_tags(db, items)
    return DocumentListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/scan", response_model=DocumentScanResponse)
def scan_documents(
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: Annotated[
        str | None,
        Query(min_length=1, max_length=CURSOR_MAX_LENGTH),
    ] = None,
    keyword: Annotated[
        str | None,
        Query(max_length=DOCUMENT_SEARCH_KEYWORD_MAX_LENGTH),
    ] = None,
    source_type: DocumentSourceType | None = None,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    tag: Annotated[str | None, Query(max_length=TAG_NAME_MAX_LENGTH)] = None,
) -> DocumentScanResponse:
    decoded_cursor = (
        decode_timestamp_id_cursor(
            cursor,
            expected_kind=DOCUMENT_SCAN_CURSOR_KIND,
        )
        if cursor is not None
        else None
    )
    items, next_cursor = document_service.scan_documents(
        db=db,
        user_id=user_id,
        page_size=page_size,
        cursor=decoded_cursor,
        keyword=keyword,
        source_type=source_type,
        status=status_filter,
        tag=tag,
    )
    document_service.attach_tags(db, items)
    return DocumentScanResponse(
        items=items,
        next_cursor=(
            encode_timestamp_id_cursor(DOCUMENT_SCAN_CURSOR_KIND, next_cursor)
            if next_cursor is not None
            else None
        ),
    )


@router.get("/stats", response_model=DocumentStatsRead)
def document_stats(
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> DocumentStatsRead:
    return document_service.get_document_stats(db, user_id)


@router.get("/{document_id}/related", response_model=list[RelatedDocumentRead])
def related_documents(
    document_id: UUID,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[RelatedDocumentRead]:
    try:
        return document_service.find_related_documents(
            db,
            user_id,
            document_id,
            limit=limit,
        )
    except document_service.RelatedDocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except document_service.RelatedDocumentUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{document_id}/export.md")
def export_document_markdown(
    document_id: UUID,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> Response:
    result = document_service.export_document_markdown(
        db,
        user_id,
        document_id,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
    filename, markdown = result
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                "attachment; filename=\"document.md\"; "
                f"filename*=UTF-8''{url_quote(filename)}"
            ),
            "Cache-Control": "no-store",
        },
    )


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: UUID,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
    content_offset: Annotated[
        int,
        Query(ge=0, le=DOCUMENT_DETAIL_CONTENT_OFFSET_MAX),
    ] = 0,
    content_limit: Annotated[
        int,
        Query(ge=1, le=DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH),
    ] = DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH,
) -> DocumentRead:
    document = document_service.get_document_detail(
        db,
        user_id,
        document_id,
        content_offset=content_offset,
        content_limit=content_limit,
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
    document_service.attach_tags(db, [document])
    return document


@router.patch("/{document_id}", response_model=DocumentRead)
def update_document(
    document_id: UUID,
    payload: DocumentUpdate,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> DocumentRead:
    updated_id = document_service.update_document(db, user_id, document_id, payload)
    if updated_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
    document = document_service.get_document_detail(db, user_id, updated_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
    document_service.attach_tags(db, [document])
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: UUID,
    request: Request,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> None:
    try:
        deleted = document_service.delete_document(db, user_id, document_id)
    except document_service.DocumentStorageProvenanceError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
    storage_deletion_wakeup = getattr(
        request.app.state,
        "storage_deletion_wakeup",
        None,
    )
    if isinstance(storage_deletion_wakeup, StorageDeletionWakeup):
        storage_deletion_wakeup.notify()


def _detect_source_type(filename: str, content_type: str | None) -> DocumentSourceType:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    normalized_content_type = (content_type or "").lower()
    if suffix == "pdf" or content_type == "application/pdf":
        return DocumentSourceType.PDF
    if suffix in {"md", "markdown"}:
        return DocumentSourceType.MARKDOWN
    if suffix == "docx" or normalized_content_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        return DocumentSourceType.DOCX
    if suffix in {"html", "htm"} or normalized_content_type == "text/html":
        return DocumentSourceType.HTML
    if suffix in {"xlsx", "xlsm"} or normalized_content_type in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel.sheet.macroenabled.12",
    }:
        return DocumentSourceType.EXCEL
    if suffix == "epub" or normalized_content_type == "application/epub+zip":
        return DocumentSourceType.EPUB
    if suffix == "txt" or normalized_content_type.startswith("text/"):
        return DocumentSourceType.TXT
    if suffix in {"png", "jpg", "jpeg", "webp", "bmp", "gif", "tif", "tiff"} or normalized_content_type.startswith(
        "image/"
    ):
        return DocumentSourceType.IMAGE
    if suffix in {"mp3", "wav", "m4a", "aac", "ogg", "opus", "flac"} or normalized_content_type.startswith("audio/"):
        return DocumentSourceType.AUDIO
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="暂不支持的文件类型")


def _reject_unavailable_media_upload(source_type: DocumentSourceType) -> None:
    if (
        source_type == DocumentSourceType.IMAGE
        and settings.ocr_provider == "disabled"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "图片 OCR 尚未启用。请先在服务端配置 OCR Provider，"
                "或改为上传 TXT、Markdown、PDF。"
            ),
        )
    if (
        source_type == DocumentSourceType.AUDIO
        and settings.speech_to_text_provider == "disabled"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "语音转文字尚未启用。请先在服务端配置语音转文字 Provider，"
                "或改为上传 TXT、Markdown、PDF。"
            ),
        )


def _title_from_filename(filename: str) -> str:
    name = filename.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return stem[:255] or "未命名资料"


def _parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    parsed = [
        part.strip()
        for part in value.replace("，", ",").split(",")
        if part.strip()
    ]
    try:
        return tag_service.normalize_document_tag_names(parsed)
    except tag_service.DocumentTagValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


def _rollback_upload_transaction(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        logger.warning("Failed to roll back an upload transaction", exc_info=True)
