"""Train a quick LSTM forecaster on per-region time series.

This script prepares sliding sequences from the synthetic multi-region CSV,
trains a soil-moisture forecaster, and saves the model + normalization stats.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
except Exception as exc:  # pragma: no cover - optional dependency guard
    raise SystemExit(f'Torch is required for this script: {exc}')

from dashboard.prediction_engine.lstm_forecaster import DroughtLSTM


FEATURE_COLS = [
    'soil_moisture_pct',
    'rainfall_mm',
    'temp_max_c',
    'temp_min_c',
    'humidity_pct',
    'wind_speed_ms',
    'solar_radiation_wm2',
    'ndvi',
    'lst_c',
    'etc_mm',
]


def build_sequences(df: pd.DataFrame, sequence_length: int, forecast_days: int):
    sequences = []
    targets = []
    meta = []

    df = df.sort_values(['region_id', 'year_id', 'time']).copy()
    for (region_id, year_id), group in df.groupby(['region_id', 'year_id'], sort=False):
        group = group.copy()
        for col in FEATURE_COLS:
            if col not in group.columns:
                group[col] = 0.0 if col != 'etc_mm' else 3.0
        group = group[FEATURE_COLS].ffill().bfill().fillna(0)
        values = group.to_numpy(dtype=np.float32)

        if len(values) < sequence_length + forecast_days:
            continue

        for start in range(len(values) - sequence_length - forecast_days + 1):
            end = start + sequence_length
            target_index = end + forecast_days - 1
            sequences.append(values[start:end])
            targets.append(values[target_index, 0])
            meta.append((int(region_id), int(year_id), start, target_index))

    if not sequences:
        raise ValueError('Not enough grouped rows to create training sequences.')

    return np.asarray(sequences, dtype=np.float32), np.asarray(targets, dtype=np.float32), meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='scripts/sample_drought_large.csv')
    parser.add_argument('--sequence-length', type=int, default=30)
    parser.add_argument('--forecast-days', type=int, default=7)
    parser.add_argument('--epochs', type=int, default=40)
    parser.add_argument('--batch-size', type=int, default=64)
    parser.add_argument('--model-out', default='scripts/lstm_quick.pth')
    parser.add_argument('--stats-out', default='scripts/lstm_quick_stats.npz')
    args = parser.parse_args()

    df = pd.read_csv(args.input, low_memory=False)
    X, y, _ = build_sequences(df, args.sequence_length, args.forecast_days)

    cutoff = int(len(X) * 0.8)
    X_train, X_val = X[:cutoff], X[cutoff:]
    y_train, y_val = y[:cutoff], y[cutoff:]

    X_mean = X_train.mean(axis=(0, 1), keepdims=True)
    X_std = X_train.std(axis=(0, 1), keepdims=True) + 1e-8
    X_train = (X_train - X_mean) / X_std
    X_val = (X_val - X_mean) / X_std

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    train_loader = DataLoader(
        TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train)),
        batch_size=args.batch_size,
        shuffle=True,
    )
    val_loader = DataLoader(
        TensorDataset(torch.from_numpy(X_val), torch.from_numpy(y_val)),
        batch_size=args.batch_size,
        shuffle=False,
    )

    model = DroughtLSTM(input_size=len(FEATURE_COLS), hidden_size=64, num_layers=2, dropout=0.2).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.MSELoss()

    best_val_loss = float('inf')
    patience = 0
    best_path = Path(args.model_out)
    best_path.parent.mkdir(parents=True, exist_ok=True)

    for epoch in range(args.epochs):
        model.train()
        train_loss = 0.0
        for batch_X, batch_y in train_loader:
            batch_X = batch_X.to(device)
            batch_y = batch_y.to(device)
            optimizer.zero_grad()
            pred = model(batch_X)
            loss = criterion(pred, batch_y)
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item())

        model.eval()
        val_loss = 0.0
        preds = []
        actuals = []
        with torch.no_grad():
            for batch_X, batch_y in val_loader:
                batch_X = batch_X.to(device)
                batch_y = batch_y.to(device)
                pred = model(batch_X)
                val_loss += float(criterion(pred, batch_y).item())
                preds.append(pred.detach().cpu().numpy())
                actuals.append(batch_y.detach().cpu().numpy())

        train_loss /= max(1, len(train_loader))
        val_loss /= max(1, len(val_loader))
        print(f'Epoch {epoch + 1:03d} | train_loss={train_loss:.4f} | val_loss={val_loss:.4f}')

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience = 0
            torch.save(model.state_dict(), best_path)
        else:
            patience += 1
            if patience >= 8:
                break

    model.load_state_dict(torch.load(best_path, map_location=device))
    model.eval()

    preds = np.concatenate(preds) if preds else np.array([])
    actuals = np.concatenate(actuals) if actuals else np.array([])
    if len(preds):
        rmse = float(np.sqrt(np.mean((actuals - preds) ** 2)))
        mae = float(np.mean(np.abs(actuals - preds)))
        print(f'Validation RMSE: {rmse:.3f}')
        print(f'Validation MAE: {mae:.3f}')

    np.savez(args.stats_out, mean=X_mean, std=X_std, feature_cols=np.array(FEATURE_COLS, dtype=object), sequence_length=args.sequence_length, forecast_days=args.forecast_days)
    print(f'Saved model to {best_path}')
    print(f'Saved stats to {args.stats_out}')


if __name__ == '__main__':
    main()
