import numpy as np
import pandas as pd

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
except ImportError:  # pragma: no cover - optional dependency guard
    torch = None
    nn = None
    DataLoader = None
    TensorDataset = None


class DroughtLSTM(nn.Module if nn is not None else object):
    def __init__(self, input_size=10, hidden_size=64, num_layers=2, dropout=0.2):
        if nn is None:
            raise ImportError('torch is required for DroughtLSTM.')
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout,
            batch_first=True,
        )
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        last_output = lstm_out[:, -1, :]
        prediction = self.fc(last_output)
        return prediction.squeeze()


FEATURE_COLS = [
    'soil_moisture_pct', 'rainfall_mm', 'temp_max_c', 'temp_min_c',
    'humidity_pct', 'wind_speed_ms', 'solar_radiation_wm2',
    'ndvi', 'lst_c', 'etc_mm',
]

class LSTMDroughtForecaster:
    def __init__(self, sequence_length=30, n_features=None):
        self.sequence_length = sequence_length
        self.n_features = n_features if n_features is not None else len(FEATURE_COLS)
        self.model = None
        self.X_mean = None
        self.X_std = None
        self.device = None
        if torch is not None:
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    def _require_torch(self):
        if torch is None:
            raise ImportError('torch is required for LSTMDroughtForecaster. Install requirements.txt.')

    def _normalize_columns(self, df):
        df = df.copy()
        aliases = {
            'temperature_max_c': 'temp_max_c',
            'temperature_min_c': 'temp_min_c',
            'relative_humidity_percent': 'humidity_pct',
            'solar_radiation_mjm2day': 'solar_radiation_wm2',
            'soil_moisture_content_percent': 'soil_moisture_pct',
            'satellite_soil_moisture_percent': 'soil_moisture_pct',
            'land_surface_temperature_c': 'lst_c',
            'evapotranspiration_etc_mmday': 'etc_mm',
            'evapotranspiration_et0_mmday': 'et0_mm',
        }
        for source, target in aliases.items():
            if source in df.columns and target not in df.columns:
                df[target] = df[source]
        return df

    def prepare_sequences(self, df, forecast_days=7):
        self._require_torch()
        df = self._normalize_columns(df)

        for col in FEATURE_COLS:
            if col not in df.columns:
                df[col] = 3.0 if col == 'etc_mm' else 0.0

        data = df[FEATURE_COLS].ffill().bfill().fillna(0).values
        X, y = [], []

        for i in range(len(data) - self.sequence_length - forecast_days + 1):
            X.append(data[i:i + self.sequence_length])
            y.append(data[i + self.sequence_length + forecast_days - 1, 0])

        return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)

    def train(self, historical_data, forecast_days=7, epochs=100, batch_size=32):
        self._require_torch()
        X, y = self.prepare_sequences(historical_data, forecast_days)
        if len(X) == 0:
            raise ValueError('Not enough data to train LSTM forecaster.')

        split_idx = int(0.8 * len(X))
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        self.X_mean = X_train.mean(axis=(0, 1), keepdims=True)
        self.X_std = X_train.std(axis=(0, 1), keepdims=True) + 1e-8
        X_train_norm = (X_train - self.X_mean) / self.X_std
        X_val_norm = (X_val - self.X_mean) / self.X_std

        train_dataset = TensorDataset(torch.from_numpy(X_train_norm), torch.from_numpy(y_train))
        val_dataset = TensorDataset(torch.from_numpy(X_val_norm), torch.from_numpy(y_val))
        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(val_dataset, batch_size=batch_size)

        self.model = DroughtLSTM(input_size=self.n_features, hidden_size=64, num_layers=2, dropout=0.2).to(self.device)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=0.001)
        criterion = nn.MSELoss()

        best_val_loss = float('inf')
        patience_counter = 0

        for epoch in range(epochs):
            self.model.train()
            train_loss = 0
            for batch_X, batch_y in train_loader:
                batch_X, batch_y = batch_X.to(self.device), batch_y.to(self.device)
                optimizer.zero_grad()
                predictions = self.model(batch_X)
                loss = criterion(predictions, batch_y)
                loss.backward()
                optimizer.step()
                train_loss += loss.item()

            self.model.eval()
            val_loss = 0
            with torch.no_grad():
                for batch_X, batch_y in val_loader:
                    batch_X, batch_y = batch_X.to(self.device), batch_y.to(self.device)
                    predictions = self.model(batch_X)
                    val_loss += criterion(predictions, batch_y).item()

            train_loss /= max(1, len(train_loader))
            val_loss /= max(1, len(val_loader))

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                torch.save(self.model.state_dict(), f'lstm_{forecast_days}day_best.pth')
            else:
                patience_counter += 1
                if patience_counter >= 15:
                    break

        self.model.load_state_dict(torch.load(f'lstm_{forecast_days}day_best.pth', map_location=self.device))
        np.savez(f'lstm_{forecast_days}day_stats.npz', mean=self.X_mean, std=self.X_std)
        self.model.eval()
        return self

    def load(self, forecast_days=7, model_path=None, stats_path=None):
        self._require_torch()
        if model_path is None:
            model_path = f'lstm_{forecast_days}day_best.pth'
        if stats_path is None:
            stats_path = f'lstm_{forecast_days}day_stats.npz'

        self.model = DroughtLSTM(input_size=self.n_features, hidden_size=64, num_layers=2, dropout=0.2).to(self.device)
        self.model.load_state_dict(torch.load(model_path, map_location=self.device))
        self.model.eval()

        stats = np.load(stats_path)
        self.X_mean = stats['mean']
        self.X_std = stats['std']
        return self

    def predict_soil_moisture(self, last_30_days_df):
        self._require_torch()

        df = self._normalize_columns(last_30_days_df)
        for col in FEATURE_COLS:
            if col not in df.columns:
                df[col] = 3.0 if col == 'etc_mm' else 0.0

        sequence = df[FEATURE_COLS].ffill().bfill().fillna(0).values[-self.sequence_length:]
        if len(sequence) != self.sequence_length:
            raise ValueError(f'Need {self.sequence_length} days, got {len(sequence)}')

        sequence_norm = (sequence - self.X_mean.squeeze()) / self.X_std.squeeze()
        input_tensor = torch.from_numpy(sequence_norm).float().unsqueeze(0).to(self.device)

        with torch.no_grad():
            predicted = self.model(input_tensor).cpu().item()

        return max(0, min(100, round(predicted, 1)))

    def predict_risk(self, last_30_days_df, field_capacity_pct):
        predicted_soil = self.predict_soil_moisture(last_30_days_df)
        risk = (1 - min(1, predicted_soil / field_capacity_pct)) * 100
        return round(max(0, min(100, risk)), 1)

    def predict_30day_trend(self, last_30_days_df, field_capacity_pct):
        soil_values = self._normalize_columns(last_30_days_df)['soil_moisture_pct'].values
        if len(soil_values) >= 14:
            recent_trend = (soil_values[-1] - soil_values[-14]) / 14
        else:
            recent_trend = -0.2

        predicted_7d = self.predict_soil_moisture(last_30_days_df)
        current = soil_values[-1]
        decline_factor = 1.5 if predicted_7d < current else 1.0

        predicted_30d = current + (recent_trend * 30 * decline_factor)
        predicted_30d = max(0, min(100, predicted_30d))

        risk = (1 - min(1, predicted_30d / field_capacity_pct)) * 100
        return round(max(0, min(100, risk)), 1)