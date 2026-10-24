
"""FastAPI endpoints for insurance cost prediction and policy RAG."""

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from services.document_service import (
    answer_indexed_document_question,
    ingest_document,
)
from services.ml_service import predict_insurance_cost


# Configure module logger
logger = logging.getLogger(__name__)

# Initialize FastAPI application
app = FastAPI(title="Insurance Cost and Policy RAG API")


# ---------------------------
# Request models
# ---------------------------

class PredictionRequest(BaseModel):
    customer_data: dict[str, Any]


class DocumentQuestionRequest(BaseModel):
    question: str


# ---------------------------
# Health endpoint
# ---------------------------

@app.get("/health")
def health():
    """Check whether the API is running."""
    return {"status": "ok"}


# ---------------------------
# ML prediction endpoint
# ---------------------------

@app.post("/predict")
def predict(request: PredictionRequest):
    """Predict insurance cost using the trained ML model."""
    try:
        estimated_cost = predict_insurance_cost(
            request.customer_data
        )

        return {
            "estimated_insurance_cost": estimated_cost
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


# ---------------------------
# PDF upload and indexing
# ---------------------------

@app.post("/documents", status_code=201)
def upload_document(file: UploadFile = File(...)):
    """Upload a PDF and persist its embeddings in ChromaDB."""

    filename = file.filename or ""

    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=415,
            detail="Only PDF files are supported.",
        )

    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False,
        ) as temporary_file:

            temporary_path = temporary_file.name

            # Read and write in 1 MB chunks
            while chunk := file.file.read(1024 * 1024):
                temporary_file.write(chunk)

        # Existing persistent document ingestion service
        document_id = ingest_document(temporary_path)

        return {
            "document_id": document_id,
            "filename": filename,
            "status": "indexed",
        }

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    finally:
        file.file.close()

        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


# ---------------------------
# Document question answering
# ---------------------------

@app.post("/documents/{document_id}/ask")
def ask_document_question(
    document_id: str,
    request: DocumentQuestionRequest,
):
    """Answer questions using an already indexed policy document."""

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

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except Exception:
        logger.exception(
            "Document question answering failed: document_id=%s",
            document_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to answer the document question.",
        )
