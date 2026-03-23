"""
CNN–LSTM fusion placeholder: fuse FIRMS heat points with SAR structural-change rasters.

Train on labeled perimeters / expert maps, then replace FusionModelStub with a loaded checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FusionModelStub:
    """Documents the intended interface until a trained model is available."""

    name: str = "cnn_lstm_fusion_v0_stub"

    def describe(self) -> dict[str, Any]:
        return {
            "model": self.name,
            "inputs": [
                "vector: FIRMS hotspots (lat, lon, time, confidence)",
                "raster: SAR VV/VH change stack aligned to study CRS",
                "raster (optional): Phase 1 flammability / moisture proxies",
            ],
            "output": "GeoJSON polygon or linestring: active fire front",
            "status": "not_trained",
        }

    def predict(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("Train and wire ignis_twin.models.fusion.FusionModel")
