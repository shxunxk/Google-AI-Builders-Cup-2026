import pandas as pd
import numpy as np
import joblib
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.metrics import classification_report, roc_auc_score
import json

from data_prep import output_dir

df = pd.read_csv(output_dir / 'train_data.csv')

le_type = LabelEncoder()
df['type_encoded'] = le_type.fit_transform(df['type'])

df['balance_diff_orig'] = df['oldbalanceOrg'] - df['newbalanceOrig']
df['balance_diff_dest'] = df['newbalanceDest'] - df['oldbalanceDest']
df['amount_to_balance_orig'] = df['amount'] / (df['oldbalanceOrg'].replace(0, 1))
df['amount_to_balance_dest'] = df['amount'] / (df['oldbalanceDest'].replace(0, 1))
df['is_zero_balance_orig'] = (df['oldbalanceOrg'] == 0).astype(int)
df['is_zero_balance_dest'] = (df['oldbalanceDest'] == 0).astype(int)

features = ['step', 'type_encoded', 'amount', 'oldbalanceOrg', 'newbalanceOrig',
            'oldbalanceDest', 'newbalanceDest', 'balance_diff_orig', 'balance_diff_dest',
            'amount_to_balance_orig', 'amount_to_balance_dest',
            'is_zero_balance_orig', 'is_zero_balance_dest']

X = df[features]
y = df['isFraud']

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

model = GradientBoostingClassifier(
    n_estimators=100,
    learning_rate=0.1,
    max_depth=5,
    random_state=42,
    subsample=0.8
)

model.fit(X_train_scaled, y_train)

y_pred = model.predict(X_test_scaled)
y_pred_proba = model.predict_proba(X_test_scaled)[:, 1]

print("Classification Report:")
print(classification_report(y_test, y_pred))
print(f"ROC-AUC: {roc_auc_score(y_test, y_pred_proba):.4f}")

model_dir = Path('scorer/model')
model_dir.mkdir(parents=True, exist_ok=True)

joblib.dump(model, model_dir / 'model.joblib')
joblib.dump(scaler, model_dir / 'scaler.joblib')
joblib.dump(le_type, model_dir / 'label_encoder.joblib')

with open(model_dir / 'features.json', 'w') as f:
    json.dump(features, f)

with open(model_dir / 'metrics.json', 'w') as f:
    json.dump({
        'roc_auc': float(roc_auc_score(y_test, y_pred_proba)),
        'n_train': len(X_train),
        'n_test': len(X_test),
        'fraud_rate_train': float(y_train.mean()),
        'fraud_rate_test': float(y_test.mean())
    }, f, indent=2)

print(f"Model saved to {model_dir}")