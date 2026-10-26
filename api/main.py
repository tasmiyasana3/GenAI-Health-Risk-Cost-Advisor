
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

The API runs locally during development. Authentication and
document ownership will be added before public deployment.
"""

import logging
import os
import tempfile

from pathlib import Path
from typing import Annotated, Any

from fastapi.openapi.utils import get_openapi
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
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
)
# Register authentication endpoints with the main API.
app.include_router(auth_router)

# Resource limits for local development.
MAX_UPLOAD_FILES = 3
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# A standard PDF begins with these bytes.
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

                # Validate the PDF signature.
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
        # Clean up if validation or writing fails.
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
# MULTIPLE PDF UPLOAD
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
):
    """
    Upload and index one to three PDFs in a single request.

    FastAPI automatically treats UploadFile as a multipart
    file input. Swagger should display a file picker.

    Each successfully indexed PDF receives:
        - A unique document ID
        - Its own ChromaDB collection
        - A PostgreSQL metadata record

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
                # Validate and save the uploaded PDF.
                temporary_path = save_uploaded_pdf(upload)

                # Use the existing document indexing service.
                document_id = ingest_document(
                    pdf_path=temporary_path,
                    filename=filename,
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
# DOCUMENT LISTING
# =============================================================================

@app.get("/documents", tags=["Documents"])
def list_uploaded_documents():
    """List documents registered in PostgreSQL."""

    try:
        return {
            "documents": list_indexed_documents()
        }

    except Exception as error:
        logger.exception("Unable to list documents.")

        raise HTTPException(
            status_code=500,
            detail="Unable to list documents.",
        ) from error


# =============================================================================
# MULTI-DOCUMENT QUESTION ANSWERING
# =============================================================================

@app.post(
    "/documents/ask",
    tags=["Document Questions"],
    summary="Ask questions across multiple documents",
)
def ask_multiple_documents(
    request: MultiDocumentQuestionRequest,
):
    """
    Search indexed PDFs, rerank relevant passages and
    generate a grounded answer using Gemini.
    """

    try:
        result = answer_multi_document_question(
            question=request.question,
            document_ids=request.document_ids,
        )

        return {
            "question": request.question,
            **result,
        }

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
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
# SINGLE DOCUMENT OPERATIONS
# =============================================================================

@app.get("/documents/{document_id}", tags=["Documents"])
def get_document_by_id(document_id: str):
    """Get metadata for one indexed document."""

    try:
        metadata = get_document_metadata(document_id)

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
def delete_document(document_id: str):
    """Delete an indexed PDF and its metadata."""

    try:
        deleted = delete_indexed_document(document_id)

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
):
    """Answer a question about one indexed PDF."""

    try:
        answer = answer_indexed_document_question(
            document_id=document_id,
            question=request.question,
        )

        return {
            "document_id": document_id,
            "question": request.question,
            "answer": answer,
        }

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
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

        # Use the binary file format recognized by Swagger UI.
        file_items["type"] = "string"
        file_items["format"] = "binary"

        # Remove the alternative representation that Swagger
        # currently renders as an ordinary string field.
        file_items.pop("contentMediaType", None)

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi