#!/bin/bash
# Local API Test Script
# Tests the scorer API locally before deployment

set -e

echo "=== Testing Scorer API Locally ==="
echo ""

# Start the API server in background
echo "Starting API server..."
cd scorer
python -m uvicorn main:app --host 0.0.0.0 --port 8080 &
SERVER_PID=$!
cd ..

# Wait for server to start
sleep 3

# Test health endpoint
echo "Testing /health endpoint..."
curl -s http://localhost:8080/health | jq .

# Test single transaction scoring
echo ""
echo "Testing /score endpoint..."
curl -s -X POST http://localhost:8080/score \
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
    }' | jq .

# Test batch scoring
echo ""
echo "Testing /score/batch endpoint..."
curl -s -X POST http://localhost:8080/score/batch \
    -H "Content-Type: application/json" \
    -d '{
        "transactions": [
            {
                "step": 1,
                "type": "CASH_OUT",
                "amount": 50000.0,
                "nameOrig": "C123456789",
                "oldbalanceOrg": 50000.0,
                "newbalanceOrig": 0.0,
                "nameDest": "C987654321",
                "oldbalanceDest": 0.0,
                "newbalanceDest": 0.0
            },
            {
                "step": 1,
                "type": "PAYMENT",
                "amount": 100.0,
                "nameOrig": "C111111111",
                "oldbalanceOrg": 10000.0,
                "newbalanceOrig": 9900.0,
                "nameDest": "M222222222",
                "oldbalanceDest": 5000.0,
                "newbalanceDest": 5100.0
            }
        ]
    }' | jq .

# Stop server
echo ""
echo "Stopping server..."
kill $SERVER_PID

echo ""
echo "=== Local Testing Complete ==="