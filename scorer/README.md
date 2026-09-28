# Immune City Fraud Scorer

Cloud Run service for real-time fraud scoring using a Vertex AI-compatible Gradient Boosting classifier.

## Architecture

```
Pub/Sub (transaction stream) → Cloud Run: Scorer → Flagged transactions → Defender Agent / Courtroom / FinCity
```

## Quick Start

### Local Development

```bash
# Install dependencies
pip install -r scorer/requirements.txt

# Train model (generates model/ directory)
python scorer/train.py

# Test model
python scorer/test_model.py

# Start API server
cd scorer && python -m uvicorn main:app --reload --port 8080
```

### API Endpoints

- `GET /health` - Health check
- `POST /score` - Score single transaction
- `POST /score/batch` - Score multiple transactions

### Example Request

```bash
curl -X POST http://localhost:8080/score \
  -H "Content-Type: application/json" \
  -d '{
    "step": 1,
    "type": "CASH_OUT",
    "amount": 50000.0,
    "nameOrig": "C123456789",
    "oldbalanceOrg": 50000.0,
    "newbalanceOrig": 0.0,
    "nameDest": "C987654321",
    "oldbalanceDest": 0.0,
    "newbalanceDest": 0.0
  }'
```

### Example Response

```json
{
  "transaction_id": "C123456789_C987654321_0",
  "fraud_probability": 0.8472,
  "is_fraud": true,
  "risk_level": "HIGH"
}
```

## Deployment

### Cloud Run (Self-hosted)

```bash
# Build and deploy
./deploy.sh YOUR_PROJECT_ID us-central1 immune-city-scorer
```

### Vertex AI (Managed Endpoint)

```bash
# Deploy to Vertex AI
./deploy_vertex_ai.sh YOUR_PROJECT_ID us-central1 immune-city-fraud-scorer
```

## Model Details

- **Algorithm**: Gradient Boosting Classifier (scikit-learn)
- **Features**: 13 engineered features from raw transaction data
- **Training Data**: 10,000 synthetic UPI transactions (3% fraud rate)
- **Performance**: ROC-AUC ~0.69 on test set

## Features

1. `step` - Time step (1-744)
2. `type_encoded` - Transaction type (PAYMENT, TRANSFER, CASH_OUT, CASH_IN, DEBIT)
3. `amount` - Transaction amount
4. `oldbalanceOrg` - Origin account balance before
5. `newbalanceOrig` - Origin account balance after
6. `oldbalanceDest` - Destination account balance before
7. `newbalanceDest` - Destination account balance after
8. `balance_diff_orig` - Origin balance change
9. `balance_diff_dest` - Destination balance change
10. `amount_to_balance_orig` - Amount / origin balance ratio
11. `amount_to_balance_dest` - Amount / destination balance ratio
12. `is_zero_balance_orig` - Origin account empty flag
13. `is_zero_balance_dest` - Destination account empty flag

## Risk Levels

- **HIGH**: fraud_probability >= 0.7
- **MEDIUM**: fraud_probability >= 0.3
- **LOW**: fraud_probability < 0.3