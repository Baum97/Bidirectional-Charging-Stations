import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

# --- load data ---
df = pd.read_csv("sumo_data.csv")
X = df[['x_position', 'y_position', 'mean_speed', 'vehicle_density', 'avg_battery_drop', 'stop_frequency']].values
y = df[['charging_score']].values

X_tensor = torch.tensor(X, dtype=torch.float32)
y_tensor = torch.tensor(y, dtype=torch.float32)

dataset = TensorDataset(X_tensor, y_tensor)
loader = DataLoader(dataset, batch_size=64, shuffle=True)

# --- define network ---
class ChargingStationNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(6, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
            nn.Sigmoid()
        )

    def forward(self, x):
        return self.net(x)

model = ChargingStationNet()
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
criterion = nn.MSELoss()

# --- training ---
for epoch in range(50):
    for X_batch, y_batch in loader:
        pred = model(X_batch)
        loss = criterion(pred, y_batch)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    print(f"Epoch {epoch+1}, Loss: {loss.item():.4f}")

# --- memorize ---
torch.save(model.state_dict(), "charging_model.pt")
print("✅ Modell gespeichert.")

# --- demonstration ---
# Neue Positionen auswerten
test = torch.tensor([[150.0, 220.0, 30.0, 12.0, 0.3, 5.0]], dtype=torch.float32)
score = model(test).item()
print(f"Vorhergesagter Eignungsscore: {score:.3f}")
