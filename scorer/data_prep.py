import pandas as pd
import numpy as np
from pathlib import Path

np.random.seed(42)

df = pd.read_csv('data/transaction_data.csv')

sample_size = 10000
df_sample = df.sample(n=min(sample_size, len(df)), random_state=42).copy()

df_sample['isFraud'] = 0

fraud_indices = df_sample.sample(n=int(sample_size * 0.02), random_state=42).index
df_sample.loc[fraud_indices, 'isFraud'] = 1

cash_out_fraud = df_sample[(df_sample['type'] == 'CASH_OUT') & (df_sample['amount'] > df_sample['amount'].quantile(0.95))].index
df_sample.loc[cash_out_fraud[:100], 'isFraud'] = 1

transfer_fraud = df_sample[(df_sample['type'] == 'TRANSFER') & (df_sample['amount'] > df_sample['amount'].quantile(0.98))].index
df_sample.loc[transfer_fraud[:50], 'isFraud'] = 1

output_dir = Path('scorer/data')
output_dir.mkdir(parents=True, exist_ok=True)

df_sample.to_csv(output_dir / 'train_data.csv', index=False)

print(f"Total samples: {len(df_sample)}")
print(f"Fraud samples: {df_sample['isFraud'].sum()}")
print(f"Fraud rate: {df_sample['isFraud'].mean():.4f}")
print(f"Saved to {output_dir}/train_data.csv")