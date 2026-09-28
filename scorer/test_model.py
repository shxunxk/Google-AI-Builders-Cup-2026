import json
import os
from pathlib import Path

import pandas as pd
import joblib

MODEL_DIR = Path('scorer/model')

model = joblib.load(MODEL_DIR / 'model.joblib')
scaler = joblib.load(MODEL_DIR / 'scaler.joblib')
le_type = joblib.load(MODEL_DIR / 'label_encoder.joblib')

with open(MODEL_DIR / 'features.json') as f:
    features = json.load(f)

test_transactions = [
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
    },
    {
        "step": 2,
        "type": "TRANSFER",
        "amount": 25000.0,
        "nameOrig": "C333333333",
        "oldbalanceOrg": 25000.0,
        "newbalanceOrig": 0.0,
        "nameDest": "C444444444",
        "oldbalanceDest": 0.0,
        "newbalanceDest": 0.0
    }
]

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    print("Before transform, types:", df['type'].values)
    df['type_encoded'] = le_type.transform(df['type'])
    print("After transform, type_encoded:", df['type_encoded'].values)
    df['balance_diff_orig'] = df['oldbalanceOrg'] - df['newbalanceOrig']
    df['balance_diff_dest'] = df['newbalanceDest'] - df['oldbalanceDest']
    df['amount_to_balance_orig'] = df['amount'] / (df['oldbalanceOrg'].replace(0, 1))
    df['amount_to_balance_dest'] = df['amount'] / (df['oldbalanceDest'].replace(0, 1))
    df['is_zero_balance_orig'] = (df['oldbalanceOrg'] == 0).astype(int)
    df['is_zero_balance_dest'] = (df['oldbalanceDest'] == 0).astype(int)
    result = df[features]
    print("Result dtypes:", result.dtypes.to_dict())
    print("Result NaN:", result.isna().sum().sum())
    return result

df = pd.DataFrame(test_transactions)
df_features = engineer_features(df)
print("Features:", df_features)
print("NaN count:", df_features.isna().sum().sum())
X_scaled = scaler.transform(df_features.values)
print("Scaled:", X_scaled)
print("Scaled NaN count:", pd.DataFrame(X_scaled).isna().sum().sum())
probas = model.predict_proba(X_scaled)[:, 1]
preds = (probas >= 0.5).astype(int)

for i, (txn, proba, pred) in enumerate(zip(test_transactions, probas, preds)):
    risk = 'HIGH' if proba >= 0.7 else 'MEDIUM' if proba >= 0.3 else 'LOW'
    print(f"Transaction {i+1}: {txn['type']} ${txn['amount']:,.2f}")
    print(f"  Fraud Probability: {proba:.4f}")
    print(f"  Is Fraud: {bool(pred)}")
    print(f"  Risk Level: {risk}")
    print()