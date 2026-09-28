# Local API Test Script (PowerShell)
# Tests the scorer API locally before deployment

Write-Host "=== Testing Scorer API Locally ===" -ForegroundColor Green
Write-Host ""

# Start the API server in background
Write-Host "Starting API server..." -ForegroundColor Yellow
$serverProcess = Start-Process python -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080" -WorkingDirectory "scorer" -PassThru

# Wait for server to start
Start-Sleep -Seconds 3

try {
    # Test health endpoint
    Write-Host "Testing /health endpoint..." -ForegroundColor Yellow
    $health = Invoke-RestMethod -Uri "http://localhost:8080/health" -Method Get
    $health | ConvertTo-Json | Write-Host

    # Test single transaction scoring
    Write-Host "`nTesting /score endpoint..." -ForegroundColor Yellow
    $singleBody = @{
        step = 1
        type = "CASH_OUT"
        amount = 50000.0
        nameOrig = "C123456789"
        oldbalanceOrg = 50000.0
        newbalanceOrig = 0.0
        nameDest = "C987654321"
        oldbalanceDest = 0.0
        newbalanceDest = 0.0
    } | ConvertTo-Json -Depth 5
    
    $singleResult = Invoke-RestMethod -Uri "http://localhost:8080/score" -Method Post -Body $singleBody -ContentType "application/json"
    $singleResult | ConvertTo-Json -Depth 5 | Write-Host

    # Test batch scoring
    Write-Host "`nTesting /score/batch endpoint..." -ForegroundColor Yellow
    $batchBody = @{
        transactions = @(
            @{
                step = 1
                type = "CASH_OUT"
                amount = 50000.0
                nameOrig = "C123456789"
                oldbalanceOrg = 50000.0
                newbalanceOrig = 0.0
                nameDest = "C987654321"
                oldbalanceDest = 0.0
                newbalanceDest = 0.0
            },
            @{
                step = 1
                type = "PAYMENT"
                amount = 100.0
                nameOrig = "C111111111"
                oldbalanceOrg = 10000.0
                newbalanceOrig = 9900.0
                nameDest = "M222222222"
                oldbalanceDest = 5000.0
                newbalanceDest = 5100.0
            }
        )
    } | ConvertTo-Json -Depth 5
    
    $batchResult = Invoke-RestMethod -Uri "http://localhost:8080/score/batch" -Method Post -Body $batchBody -ContentType "application/json"
    $batchResult | ConvertTo-Json -Depth 5 | Write-Host
}
catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    # Stop server
    Write-Host "`nStopping server..." -ForegroundColor Yellow
    Stop-Process -Id $serverProcess.Id -Force
}

Write-Host "`n=== Local Testing Complete ===" -ForegroundColor Green