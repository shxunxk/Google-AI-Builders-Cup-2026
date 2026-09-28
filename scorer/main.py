import os
import json
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn

MODEL_DIR = Path(os.environ.get('MODEL_DIR', '/app/model'))

model = None
scaler = None
le_type = None
features = None


class TransactionRequest(BaseModel):
    step: int = Field(..., ge=1, le=744)
    type: str = Field(..., pattern='^(PAYMENT|TRANSFER|CASH_OUT|CASH_IN|DEBIT)$')
    amount: float = Field(..., gt=0)
    nameOrig: str
    oldbalanceOrg: float = Field(..., ge=0)
    newbalanceOrig: float = Field(..., ge=0)
    nameDest: str
    oldbalanceDest: float = Field(..., ge=0)
    newbalanceDest: float = Field(..., ge=0)


class BatchRequest(BaseModel):
    transactions: List[TransactionRequest]


class ScoreResponse(BaseModel):
    transaction_id: str
    fraud_probability: float
    is_fraud: bool
    risk_level: str


class BatchResponse(BaseModel):
    scores: List[ScoreResponse]


def load_model():
    global model, scaler, le_type, features
    try:
        model = joblib.load(MODEL_DIR / 'model.joblib')
        scaler = joblib.load(MODEL_DIR / 'scaler.joblib')
        le_type = joblib.load(MODEL_DIR / 'label_encoder.joblib')
        with open(MODEL_DIR / 'features.json') as f:
            features = json.load(f)
        print(f"Model loaded successfully from {MODEL_DIR}")
    except Exception as e:
        print(f"Error loading model: {e}")
        raise


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['type_encoded'] = le_type.transform(df['type'])
    df['balance_diff_orig'] = df['oldbalanceOrg'] - df['newbalanceOrig']
    df['balance_diff_dest'] = df['newbalanceDest'] - df['oldbalanceDest']
df['amount_to_balance_orig'] = df['amount'] / (df['oldbalanceOrg'].replace(0, 1))
df['amount_to_balance_dest'] = df['amount'] / (df['oldbalanceDest'].replace(0, 1))
    df['is_zero_balance_orig'] = (df['oldbalanceOrg'] == 0).astype(int)
    df['is_zero_balance_dest'] = (df['oldbalanceDest'] == 0).astype(int)
    return df[features]


def predict_fraud(transactions: List[Dict]) -> List[Dict]:
    df = pd.DataFrame(transactions)
    df_features = engineer_features(df)
    X_scaled = scaler.transform(df_features)
    probas = model.predict_proba(X_scaled)[:, 1]
    preds = (probas >= 0.5).astype(int)
    
    results = []
    for i, (proba, pred) in enumerate(zip(probas, preds)):
        risk_level = 'HIGH' if proba >= 0.7 else 'MEDIUM' if proba >= 0.3 else 'LOW'
        results.append({
            'transaction_id': f"{transactions[i].get('nameOrig', '')}_{transactions[i].get('nameDest', '')}_{i}",
            'fraud_probability': float(proba),
            'is_fraud': bool(pred),
            'risk_level': risk_level
        })
    return results


app = FastAPI(title="Immune City Fraud Scorer", version="1.0.0")


@app.on_event("startup")
async def startup_event():
    load_model()


@app.get("/health")
async def health_check():
    return {"status": "healthy", "model_loaded": model is not None}


@app.post("/score", response_model=ScoreResponse)
async def score_transaction(request: TransactionRequest):
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    try:
        result = predict_fraud([request.dict()])[0]
        return ScoreResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/score/batch", response_model=BatchResponse)
async def score_batch(request: BatchRequest):
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    try:
        transactions = [t.dict() for t in request.transactions]
        results = predict_fraud(transactions)
        return BatchResponse(scores=[ScoreResponse(**r) for r in results])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)