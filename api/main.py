
"""
FastAPI backend for the Insurance Cost and Policy RAG application.

Responsibilities
----------------
1. Predict insurance costs using the trained ML pipeline.
2. Upload and index up to three PDF documents in one request.
3. Store document metadata in PostgreSQL.
4. Retrieve relevant passages from ChromaDB.
5. Answer questions using one or multiple indexed documents.
6. List, inspect and delete indexed documents.
7. Enforce verified user/session ownership on document routes.

Document identities are obtained only through the server-side
authentication dependency, never from user-supplied IDs.
"""

import logging
import os
import tempfile
from contextlib import asynccontextmanager

from services.document_lifecycle import (
    start_cleanup_scheduler,
    stop_cleanup_scheduler,
)

from pathlib import Path
from typing import Any

from fastapi.openapi.utils import get_openapi
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from api.auth_dependencies import AuthenticatedUser, get_current_user
from api.auth_routes import router as auth_router

from services.ml_service import predict_insurance_cost

from services.document_service import (
    answer_indexed_document_question,
    answer_multi_document_question,
    delete_indexed_document,
    get_document_metadata,
    ingest_document,
    list_indexed_documents,
)

# =============================================================================
# APPLICATION LIFESPAN - PHASE 4.4.6
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    PURPOSE
    -------
    Manage the startup and shutdown of temporary document cleanup.

    ENVIRONMENT / CONFIGURATION
    ---------------------------
    ENABLE_DOCUMENT_CLEANUP controls whether cleanup starts.

    DOCUMENT_CLEANUP_INTERVAL_SECONDS controls cleanup frequency.

    DEPENDENCIES
    ------------
    services.document_lifecycle

    RESPONSIBILITIES / WHAT WE TEST
    -------------------------------
    1. Start cleanup when FastAPI starts.
    2. Stop cleanup when FastAPI shuts down.
    3. Preserve all existing API endpoints.

    SECURITY NOTES
    --------------
    Cleanup remains disabled unless explicitly enabled.
    """
    start_cleanup_scheduler()

    try:
        yield
    finally:
        stop_cleanup_scheduler()

# =============================================================================
# APPLICATION CONFIGURATION
# =============================================================================

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Insurance Cost and Policy RAG API",
    description=(
        "REST API for insurance cost prediction and "
        "AI-powered analysis of multiple insurance documents."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

# Register existing authentication endpoints.
app.include_router(auth_router)

# Resource limits for local development.
MAX_UPLOAD_FILES = 3
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

PDF_SIGNATURE = b"%PDF-"


# =============================================================================
# REQUEST MODELS
# =============================================================================

class PredictionRequest(BaseModel):
    """Customer information used for insurance cost prediction."""

    customer_data: dict[str, Any]


class DocumentQuestionRequest(BaseModel):
    """Question about one indexed PDF."""

    question: str


class MultiDocumentQuestionRequest(BaseModel):
    """Question about all indexed PDFs or a selected subset."""

    question: str
    document_ids: list[str] | None = None


# =============================================================================
# PDF VALIDATION AND TEMPORARY STORAGE
# =============================================================================

def validate_file_count(files: list[UploadFile]) -> None:
    """Allow between one and three PDFs in each upload request."""

    if not 1 <= len(files) <= MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Upload between 1 and "
                f"{MAX_UPLOAD_FILES} PDF files."
            ),
        )


def save_uploaded_pdf(upload: UploadFile) -> str:
    """
    Validate a PDF and save it to a temporary file.

    Reading in chunks prevents loading the entire PDF into memory.

    Returns
    -------
    str
        Absolute path of the temporary PDF.
    """

    filename = Path(upload.filename or "").name

    if not filename.lower().endswith(".pdf"):
        raise ValueError(
            f"{filename}: Only PDF files are supported."
        )

    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".pdf",
            delete=False,
        ) as temporary_file:

            temporary_path = temporary_file.name
            total_bytes = 0
            first_chunk = True

            while True:
                chunk = upload.file.read(1024 * 1024)

                if not chunk:
                    break

                if first_chunk:
                    if not chunk.startswith(PDF_SIGNATURE):
                        raise ValueError(
                            f"{filename}: Invalid PDF file."
                        )

                    first_chunk = False

                total_bytes += len(chunk)

                if total_bytes > MAX_FILE_SIZE_BYTES:
                    raise ValueError(
                        f"{filename}: File exceeds "
                        f"{MAX_FILE_SIZE_MB} MB."
                    )

                temporary_file.write(chunk)

            if total_bytes == 0:
                raise ValueError(
                    f"{filename}: The PDF is empty."
                )

        return temporary_path

    except Exception:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)

        raise


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.get("/health", tags=["System"])
def health_check():
    """Check whether the API server is running."""

    return {"status": "ok"}


# =============================================================================
# INSURANCE COST PREDICTION
# =============================================================================

@app.post("/predict", tags=["Prediction"])
def predict(request: PredictionRequest):
    """Estimate insurance cost using the existing ML pipeline."""

    try:
        prediction = predict_insurance_cost(
            request.customer_data
        )

        return {
            "estimated_insurance_cost": prediction
        }

    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=503,
            detail=str(error),
        ) from error


# =============================================================================
# AUTHENTICATED MULTIPLE PDF UPLOAD
# =============================================================================

@app.post(
    "/documents",
    status_code=201,
    tags=["Documents"],
    summary="Upload up to three PDF documents",
)
def upload_documents(
    files: list[UploadFile] = File(
        ...,
        description="Select up to three PDF files.",
    ),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Upload and index one to three PDFs in a single request.

    The authenticated user/session is determined by the server.
    Client-supplied ownership identifiers are not accepted.

    If one file fails, other files can still be processed.
    """

    validate_file_count(files)

    results = []

    try:
        for upload in files:

            filename = Path(
                upload.filename or "unknown.pdf"
            ).name

            temporary_path = None

            try:
                temporary_path = save_uploaded_pdf(upload)

                document_id = ingest_document(
                    pdf_path=temporary_path,
                    filename=filename,
                    user_id=current_user.user_id,
                    session_id=current_user.session_id,
                )

                logger.info(
                    "Indexed PDF: filename=%s document_id=%s",
                    filename,
                    document_id,
                )

                results.append(
                    {
                        "filename": filename,
                        "document_id": document_id,
                        "status": "ready",
                    }
                )

            except ValueError as error:
                logger.warning(
                    "PDF validation failed: %s",
                    error,
                )

                results.append(
                    {
                        "filename": filename,
                        "status": "failed",
                        "error": str(error),
                    }
                )

            except Exception:
                logger.exception(
                    "PDF indexing failed: %s",
                    filename,
                )

                results.append(
                    {
                        "filename": filename,
                        "status": "failed",
                        "error": (
                            "Document processing failed. "
                            "Check the server logs."
                        ),
                    }
                )

            finally:
                upload.file.close()

                if (
                    temporary_path
                    and os.path.exists(temporary_path)
                ):
                    os.unlink(temporary_path)

    finally:
        for upload in files:
            upload.file.close()

    successful = sum(
        result["status"] == "ready"
        for result in results
    )

    return {
        "total_files": len(results),
        "successful": successful,
        "failed": len(results) - successful,
        "documents": results,
    }


# =============================================================================
# AUTHENTICATED DOCUMENT LISTING
# =============================================================================

@app.get("/documents", tags=["Documents"])
def list_uploaded_documents(
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """List only documents belonging to the authenticated session."""

    try:
        return {
            "documents": list_indexed_documents(
                user_id=current_user.user_id,
                session_id=current_user.session_id,
            )
        }

    except Exception as error:
        logger.exception("Unable to list documents.")

        raise HTTPException(
            status_code=500,
            detail="Unable to list documents.",
        ) from error


# =============================================================================
# AUTHENTICATED MULTI-DOCUMENT QUESTION ANSWERING
# =============================================================================

@app.post(
    "/documents/ask",
    tags=["Document Questions"],
    summary="Ask questions across multiple documents",
)
def ask_multiple_documents(
    request: MultiDocumentQuestionRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Search only authorized PDFs, rerank passages and generate
    a grounded answer using Gemini.
    """

    try:
        result = answer_multi_document_question(
            question=request.question,
            document_ids=request.document_ids,
            user_id=current_user.user_id,
            session_id=current_user.session_id,
        )

        return {
            "question": request.question,
            **result,
        }

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        ) from error

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except Exception as error:
        logger.exception("Multi-document question failed.")

        raise HTTPException(
            status_code=500,
            detail="Unable to answer the document question.",
        ) from error


# =============================================================================
# AUTHENTICATED SINGLE DOCUMENT OPERATIONS
# =============================================================================

@app.get("/documents/{document_id}", tags=["Documents"])
def get_document_by_id(
    document_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Get metadata only for a document in the authenticated session."""

    try:
        metadata = get_document_metadata(
            document_id=document_id,
            user_id=current_user.user_id,
            session_id=current_user.session_id,
        )

        if metadata is None:
            raise HTTPException(
                status_code=404,
                detail="Document not found.",
            )

        return metadata

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except HTTPException:
        raise

    except Exception as error:
        logger.exception("Document lookup failed.")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve document.",
        ) from error


@app.delete("/documents/{document_id}", tags=["Documents"])
def delete_document(
    document_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Delete only a document belonging to the authenticated session."""

    try:
        deleted = delete_indexed_document(
            document_id=document_id,
            user_id=current_user.user_id,
            session_id=current_user.session_id,
        )

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="Document not found.",
            )

        return {
            "document_id": document_id,
            "status": "deleted",
        }

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except HTTPException:
        raise

    except Exception as error:
        logger.exception("Document deletion failed.")

        raise HTTPException(
            status_code=500,
            detail="Unable to delete document.",
        ) from error


@app.post(
    "/documents/{document_id}/ask",
    tags=["Document Questions"],
)
def ask_single_document(
    document_id: str,
    request: DocumentQuestionRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Answer a question using only an authorized indexed PDF."""

    try:
        answer = answer_indexed_document_question(
            document_id=document_id,
            question=request.question,
            user_id=current_user.user_id,
            session_id=current_user.session_id,
        )

        return {
            "document_id": document_id,
            "question": request.question,
            "answer": answer,
        }

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        ) from error

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except Exception as error:
        logger.exception("Single-document question failed.")

        raise HTTPException(
            status_code=500,
            detail="Unable to answer the document question.",
        ) from error


# =============================================================================
# OPENAPI FILE UPLOAD SCHEMA COMPATIBILITY
# =============================================================================

def custom_openapi():
    """
    Ensure Swagger UI recognizes multiple PDF uploads.

    Some FastAPI/Pydantic/OpenAPI combinations describe uploaded
    files using contentMediaType instead of format="binary".

    Swagger UI may render those fields as text inputs rather
    than file selectors.

    This function changes only the generated API documentation.
    It does not modify file upload processing.
    """
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    upload_schema = schema.get("components", {}).get(
        "schemas", {}
    ).get("Body_upload_documents_documents_post")

    if upload_schema:
        files_property = upload_schema.get(
            "properties", {}
        ).get("files", {})

        file_items = files_property.get("items", {})

        file_items["type"] = "string"
        file_items["format"] = "binary"

        file_items.pop("contentMediaType", None)

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi