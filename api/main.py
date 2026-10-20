"""Optional FastAPI endpoint for ML predictions."""
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from services.ml_service import predict_insurance_cost

app = FastAPI(title='Insurance Cost Prediction API')

class PredictionRequest(BaseModel):
    customer_data: dict[str, Any]

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.post('/predict')
def predict(request: PredictionRequest):
    try:
        return {'estimated_insurance_cost': predict_insurance_cost(request.customer_data)}
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
