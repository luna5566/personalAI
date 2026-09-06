from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus
from app.models.embedding import ChunkEmbedding
from app.models.embedding_configuration_state import EmbeddingConfigurationState
from app.models.job import Job, JobStatus, JobType
from app.services import job_service, settings_service


EMBEDDING_CONFIGURATION_STATE_ID = 1
EMBEDDING_CONFIGURATION_LOCK_ID = 731_536_1537
REBUILDABLE_DOCUMENT_STATUSES = {
    DocumentStatus.INDEXED.value,
    DocumentStatus.FAILED.value,
}
REUSABLE_CONFIGURATION_JOB_STATUSES = {
    JobStatus.PENDING.value,
    JobStatus.RUNNING.value,
}


def reconcile_embedding_configuration(
    db: Session,
    owner_user_id: UUID,
) -> Job | None:
    fingerprint = settings_service.embedding_configuration_fingerprint()
    db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": EMBEDDING_CONFIGURATION_LOCK_ID},
    )
    state = db.get(
        EmbeddingConfigurationState,
        EMBEDDING_CONFIGURATION_STATE_ID,
        with_for_update=True,
    )
    if state is not None and state.fingerprint == fingerprint:
        db.commit()
        return None

    if state is None:
        rebuild_required = _initial_rebuild_required(
            db,
            settings_service.embedding_index_id(),
        )
        state = EmbeddingConfigurationState(
            id=EMBEDDING_CONFIGURATION_STATE_ID,
            fingerprint=fingerprint,
        )
    else:
        rebuild_required = _has_rebuildable_documents(db)
        state.fingerprint = fingerprint

    job = None
    existing_job = db.scalar(
        select(Job.id)
        .where(
            Job.job_type == JobType.REBUILD_ALL_EMBEDDINGS.value,
            Job.configuration_fingerprint == fingerprint,
            Job.status.in_(REUSABLE_CONFIGURATION_JOB_STATUSES),
        )
        .limit(1)
    )
    if rebuild_required and existing_job is None:
        job = job_service.add_job(
            db,
            owner_user_id,
            None,
            JobType.REBUILD_ALL_EMBEDDINGS,
            configuration_fingerprint=fingerprint,
        )
    db.add(state)
    db.commit()
    if job is not None:
        db.refresh(job)
    return job


def _initial_rebuild_required(db: Session, index_id: str) -> bool:
    document_without_chunks = db.scalar(
        select(Document.id)
        .where(Document.status.in_(REBUILDABLE_DOCUMENT_STATUSES))
        .where(
            ~select(DocumentChunk.id)
            .where(DocumentChunk.document_id == Document.id)
            .exists()
        )
        .limit(1)
    )
    if document_without_chunks is not None:
        return True

    inconsistent_chunk = db.scalar(
        select(DocumentChunk.id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .outerjoin(
            ChunkEmbedding,
            ChunkEmbedding.chunk_id == DocumentChunk.id,
        )
        .where(
            Document.status.in_(REBUILDABLE_DOCUMENT_STATUSES),
            or_(
                ChunkEmbedding.id.is_(None),
                ChunkEmbedding.embedding_model != index_id,
            ),
        )
        .limit(1)
    )
    return inconsistent_chunk is not None


def _has_rebuildable_documents(db: Session) -> bool:
    return (
        db.scalar(
            select(Document.id)
            .where(Document.status.in_(REBUILDABLE_DOCUMENT_STATUSES))
            .limit(1)
        )
        is not None
    )
