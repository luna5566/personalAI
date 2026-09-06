import logging
from collections.abc import Iterator
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, tuple_
from sqlalchemy.engine import Connection

from app.core.database import SessionLocal, engine
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.models.document import DocumentStatus
from app.models.job import Job
from app.models.job import JobStatus
from app.services import (
    chunking_service,
    document_service,
    embedding_service,
    enrichment_service,
    job_error_service,
    job_service,
    parsing_service,
)
from app.utils.text_cleaner import clean_text

logger = logging.getLogger(__name__)
REBUILD_DOCUMENT_KEY_BATCH_SIZE = 100
REBUILDABLE_DOCUMENT_STATUSES = (
    DocumentStatus.INDEXED.value,
    DocumentStatus.FAILED.value,
)


def process_document(
    job_id: UUID,
    document_id: UUID,
    *,
    run_token: UUID | None = None,
) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        document = document_service.get_document_by_id(db, document_id)
        if job is None:
            return
        if job.status in job_service.TERMINAL_JOB_STATUSES:
            return
        if job.status == JobStatus.CANCEL_REQUESTED.value:
            if job.run_token is not None:
                _cancel_document_processing(
                    db,
                    job_id,
                    job.run_token,
                    document_id,
                    False,
                )
            return
        recovered = run_token is not None
        execution_token = run_token or uuid4()
        heartbeat = job_service.JobHeartbeat(job_id, execution_token)
        index_ready = False
        public_error_fallback = "资料解析失败，请确认文件有效后重试"
        try:
            job_service.raise_if_cancel_requested(db, job_id)
            _claim_job_execution(
                db,
                job_id,
                execution_token,
                recovered=recovered,
                progress=10,
                message="正在解析资料",
            )
            if document is None:
                job_service.fail_active_job(
                    db,
                    job_id,
                    execution_token,
                    message="处理失败",
                    error_message="资料已删除或不存在",
                )
                return
            heartbeat.start()
            document.status = DocumentStatus.PARSING.value
            db.add(document)
            db.commit()

            parsed = parsing_service.parse_document(document)
            job_service.raise_if_job_stopped(db, job_id, execution_token)
            if not parsed.raw_text or parsed.raw_text.isspace():
                raise job_error_service.PublicJobError(
                    "资料中没有解析到可索引的文本内容"
                )
            public_error_fallback = "资料内容处理失败，请稍后重试"
            document.raw_text = parsed.raw_text
            document.cleaned_text = clean_text(parsed.raw_text)
            document.metadata_ = {**(document.metadata_ or {}), **parsed.metadata}
            document.status = DocumentStatus.CHUNKING.value
            db.add(document)
            db.commit()

            job_service.update_running_job(
                db,
                job_id,
                execution_token,
                progress=45,
                message="正在切片",
            )
            public_error_fallback = "资料切片失败，请稍后重试"
            chunk_count = chunking_service.recreate_document_chunks(
                db,
                document,
            )
            if chunk_count == 0:
                raise job_error_service.PublicJobError(
                    "资料没有可用于索引的文本切片"
                )
            job_service.raise_if_job_stopped(db, job_id, execution_token)

            job_service.update_running_job(
                db,
                job_id,
                execution_token,
                progress=70,
                message="正在生成向量索引",
            )
            public_error_fallback = (
                "资料向量索引失败，请检查 Embedding Provider 配置后重试"
            )
            _release_worker_connection(db)
            embedding_service.embed_document_chunks(db, document)
            job_service.raise_if_job_stopped(db, job_id, execution_token)
            db.commit()
            index_ready = True

            job_service.update_running_job(
                db,
                job_id,
                execution_token,
                progress=88,
                message="正在生成摘要和标签",
            )
            document.status = DocumentStatus.SUMMARIZING.value
            db.add(document)
            db.commit()
            job_service.raise_if_job_stopped(db, job_id, execution_token)
            enrichment_chunks = (
                enrichment_service.load_document_enrichment_chunks(
                    db,
                    document_id,
                )
            )
            _release_worker_connection(db)
            try:
                enrichment_service.enrich_document(
                    db,
                    document,
                    enrichment_chunks,
                )
            except enrichment_service.EnrichmentProviderError as exc:
                enrichment_service.record_enrichment_error(document, exc)
            job_service.raise_if_job_stopped(db, job_id, execution_token)
            document.status = DocumentStatus.INDEXED.value
            db.add(document)
            db.commit()

            job_service.complete_running_job(
                db,
                job_id,
                execution_token,
                "处理完成",
            )
        except job_service.JobClaimConflictError:
            db.rollback()
            return
        except job_service.JobCancelledError:
            db.rollback()
            _cancel_document_processing(
                db,
                job_id,
                execution_token,
                document_id,
                index_ready,
            )
        except Exception as exc:
            logger.warning("Document processing failed", exc_info=True)
            public_error = job_error_service.public_job_error_message(
                exc,
                public_error_fallback,
            )
            db.rollback()
            try:
                job_service.raise_if_job_stopped(db, job_id, execution_token)
            except job_service.JobClaimConflictError:
                return
            except job_service.JobCancelledError:
                _cancel_document_processing(
                    db,
                    job_id,
                    execution_token,
                    document_id,
                    index_ready,
                )
                return
            stored_document = document_service.get_document_by_id(db, document_id)
            if stored_document is not None:
                stored_document.status = DocumentStatus.FAILED.value
                stored_document.error_message = public_error
                db.add(stored_document)
                db.commit()
            stored_job = db.get(Job, job_id)
            if stored_job is not None:
                try:
                    job_service.fail_active_job(
                        db,
                        job_id,
                        execution_token,
                        message="处理失败",
                        error_message=public_error,
                    )
                except job_service.JobClaimConflictError:
                    return
                except job_service.JobCancelledError:
                    _cancel_document_processing(
                        db,
                        job_id,
                        execution_token,
                        document_id,
                        index_ready,
                    )
        finally:
            heartbeat.stop()


def _cancel_document_processing(
    db,
    job_id: UUID,
    run_token: UUID,
    document_id: UUID,
    index_ready: bool,
) -> None:
    stored_document = document_service.get_document_by_id(db, document_id)
    if stored_document is not None:
        stored_document.status = (
            DocumentStatus.INDEXED.value
            if index_ready
            else DocumentStatus.CANCELLED.value
        )
        stored_document.error_message = None
        db.add(stored_document)
        db.commit()
    message = "任务已取消，资料索引已完成" if index_ready else "资料处理已取消"
    job_service.mark_job_cancelled(db, job_id, run_token, message)


GLOBAL_REBUILD_LOCK_ID = 731_536_1536


def _claim_job_execution(
    db,
    job_id: UUID,
    run_token: UUID,
    *,
    recovered: bool,
    progress: int,
    message: str,
) -> None:
    claim = job_service.resume_job if recovered else job_service.start_job
    claim(db, job_id, run_token, progress=progress, message=message)


class _GlobalRebuildLock:
    def __init__(self) -> None:
        self._connection: Connection | None = None
        self._acquired = False

    def acquire(self) -> None:
        connection = engine.connect()
        self._connection = connection
        try:
            connection.execute(
                text("SELECT pg_advisory_lock(:lock_id)"),
                {"lock_id": GLOBAL_REBUILD_LOCK_ID},
            )
            connection.commit()
            self._acquired = True
        except Exception:
            connection.invalidate()
            connection.close()
            self._connection = None
            raise

    def release(self) -> None:
        connection = self._connection
        if connection is None:
            return
        try:
            if self._acquired:
                released = connection.scalar(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": GLOBAL_REBUILD_LOCK_ID},
                )
                connection.commit()
                if released is not True:
                    connection.invalidate()
                    logger.warning("Global rebuild lock was not owned by its connection")
        except Exception:
            connection.invalidate()
            logger.warning("Failed to release global rebuild lock", exc_info=True)
        finally:
            connection.close()
            self._connection = None
            self._acquired = False


def _rebuild_document_filters(
    user_id: UUID | None,
    created_before: datetime,
) -> list:
    filters = [
        Document.status.in_(REBUILDABLE_DOCUMENT_STATUSES),
        Document.created_at <= created_before,
    ]
    if user_id is not None:
        filters.append(Document.user_id == user_id)
    return filters


def _count_rebuild_documents(
    db,
    *,
    user_id: UUID | None,
    created_before: datetime,
) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Document)
            .where(*_rebuild_document_filters(user_id, created_before))
        )
        or 0
    )


def _iter_rebuild_documents(
    db,
    *,
    user_id: UUID | None,
    created_before: datetime,
    batch_size: int = REBUILD_DOCUMENT_KEY_BATCH_SIZE,
) -> Iterator[Document]:
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("Rebuild document batch size must be a positive integer")

    cursor: tuple[UUID, datetime, UUID] | None = None
    while True:
        key_statement = select(
            Document.user_id,
            Document.created_at,
            Document.id,
        ).where(*_rebuild_document_filters(user_id, created_before))
        if cursor is not None:
            key_statement = key_statement.where(
                tuple_(Document.user_id, Document.created_at, Document.id)
                > tuple_(*cursor)
            )
        rows = list(
            db.execute(
                key_statement.order_by(
                    Document.user_id.asc(),
                    Document.created_at.asc(),
                    Document.id.asc(),
                ).limit(batch_size)
            )
        )
        db.rollback()
        if not rows:
            return

        for row in rows:
            document = db.scalar(
                select(Document).where(
                    Document.id == row.id,
                    *_rebuild_document_filters(user_id, created_before),
                )
            )
            if document is None:
                db.rollback()
                continue
            db.expunge(document)
            db.rollback()
            yield document

        last = rows[-1]
        cursor = (last.user_id, last.created_at, last.id)


def rebuild_embeddings(
    job_id: UUID,
    user_id: UUID | None,
    *,
    run_token: UUID | None = None,
) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        if job.status in job_service.TERMINAL_JOB_STATUSES:
            return

        recovered = run_token is not None
        execution_token = run_token or uuid4()
        global_lock = _GlobalRebuildLock() if user_id is None else None
        heartbeat = job_service.JobHeartbeat(job_id, execution_token)
        rebuilt = 0
        try:
            job_service.raise_if_cancel_requested(db, job_id)
            _claim_job_execution(
                db,
                job_id,
                execution_token,
                recovered=recovered,
                progress=max(job.progress, 1) if user_id is None else 5,
                message=(
                    "正在等待全局索引重建任务"
                    if user_id is None
                    else "正在准备重建索引"
                ),
            )
            heartbeat.start()
            if user_id is None:
                global_lock.acquire()
                db.refresh(job)
                if job.status in job_service.TERMINAL_JOB_STATUSES:
                    return
                job_service.raise_if_job_stopped(db, job_id, execution_token)
                job_service.update_running_job(
                    db,
                    job_id,
                    execution_token,
                    progress=5,
                    message="正在准备重建索引",
                )
            provider = embedding_service.get_embedding_provider()
            job_service.raise_if_job_stopped(db, job_id, execution_token)
            scan_started_at = datetime.now(timezone.utc)
            total = _count_rebuild_documents(
                db,
                user_id=user_id,
                created_before=scan_started_at,
            )
            if total == 0:
                job_service.complete_running_job(
                    db,
                    job_id,
                    execution_token,
                    "没有需要重建索引的资料",
                )
                return
            _release_worker_connection(db)

            failed_count = 0
            failed_samples: list[str] = []
            documents = _iter_rebuild_documents(
                db,
                user_id=user_id,
                created_before=scan_started_at,
            )
            for index, document in enumerate(documents, start=1):
                job_service.raise_if_job_stopped(db, job_id, execution_token)
                document_id = document.id
                document_title = document.title
                progress = min(5 + int((index - 1) / total * 90), 94)
                job_service.update_running_job(
                    db,
                    job_id,
                    execution_token,
                    progress=progress,
                    message=f"正在重建索引：{document_title}",
                )
                source_text = document.cleaned_text or document.raw_text or ""
                if not source_text.strip():
                    message = "资料没有可用于重建索引的文本内容"
                    document.status = DocumentStatus.FAILED.value
                    document.error_message = message
                    db.add(document)
                    db.commit()
                    failed_count += 1
                    if len(failed_samples) < 3:
                        failed_samples.append(f"{document_title}：{message}")
                    _release_worker_connection(db)
                    continue

                try:
                    first_chunk_id = db.scalar(
                        select(DocumentChunk.id)
                        .where(DocumentChunk.document_id == document_id)
                        .order_by(DocumentChunk.chunk_index)
                        .limit(1)
                    )
                    if first_chunk_id is None:
                        chunk_count = (
                            chunking_service.recreate_document_chunks(
                                db,
                                document,
                            )
                        )
                    else:
                        chunk_count = 1
                    if chunk_count == 0:
                        raise job_error_service.PublicJobError(
                            "资料没有可用于重建索引的文本切片"
                        )
                    job_service.raise_if_job_stopped(
                        db,
                        job_id,
                        execution_token,
                    )
                    db.commit()
                    embedding_service.embed_document_chunks(
                        db,
                        document,
                        provider=provider,
                    )
                    job_service.raise_if_job_stopped(db, job_id, execution_token)
                    document.status = DocumentStatus.INDEXED.value
                    document.error_message = None
                    db.add(document)
                    db.commit()
                    rebuilt += 1
                    _release_worker_connection(db)
                except job_service.JobCancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Document embedding rebuild failed",
                        exc_info=True,
                    )
                    public_error = job_error_service.public_job_error_message(
                        exc,
                        "重建索引失败，请检查 Embedding Provider 配置后重试",
                    )
                    db.rollback()
                    job_service.raise_if_job_stopped(
                        db,
                        job_id,
                        execution_token,
                    )
                    stored_document = document_service.get_document_by_id(db, document_id)
                    if stored_document is not None:
                        stored_document.status = DocumentStatus.FAILED.value
                        stored_document.error_message = public_error
                        db.add(stored_document)
                        db.commit()
                    failed_count += 1
                    if len(failed_samples) < 3:
                        failed_samples.append(
                            f"{document_title}：{public_error}"
                        )
                    _release_worker_connection(db)

            if failed_count:
                job_service.raise_if_job_stopped(db, job_id, execution_token)
                error_summary = "；".join(failed_samples)
                if failed_count > len(failed_samples):
                    error_summary += (
                        f"；另有 {failed_count - len(failed_samples)} 份失败"
                    )
                job_service.fail_active_job(
                    db,
                    job_id,
                    execution_token,
                    message=f"已重建 {rebuilt} 份，失败 {failed_count} 份",
                    error_message=error_summary,
                )
            else:
                job_service.complete_running_job(
                    db,
                    job_id,
                    execution_token,
                    f"已重建 {rebuilt} 份资料的索引",
                )
        except job_service.JobClaimConflictError:
            db.rollback()
            return
        except job_service.JobCancelledError:
            db.rollback()
            job_service.mark_job_cancelled(
                db,
                job_id,
                execution_token,
                f"任务已取消，已重建 {rebuilt} 份资料",
            )
        except Exception as exc:
            logger.warning("Embedding rebuild job failed", exc_info=True)
            public_error = job_error_service.public_job_error_message(
                exc,
                "索引重建任务失败，请稍后重试",
            )
            db.rollback()
            try:
                job_service.raise_if_job_stopped(db, job_id, execution_token)
            except job_service.JobClaimConflictError:
                return
            except job_service.JobCancelledError:
                job_service.mark_job_cancelled(
                    db,
                    job_id,
                    execution_token,
                    f"任务已取消，已重建 {rebuilt} 份资料",
                )
                return
            try:
                job_service.fail_active_job(
                    db,
                    job_id,
                    execution_token,
                    message="重建索引失败",
                    error_message=public_error,
                )
            except job_service.JobClaimConflictError:
                return
            except job_service.JobCancelledError:
                job_service.mark_job_cancelled(
                    db,
                    job_id,
                    execution_token,
                    f"任务已取消，已重建 {rebuilt} 份资料",
                )
        finally:
            heartbeat.stop()
            if global_lock is not None:
                global_lock.release()


def _release_worker_connection(db) -> None:
    expunge_all = getattr(db, "expunge_all", None)
    if callable(expunge_all):
        expunge_all()
    db.rollback()
