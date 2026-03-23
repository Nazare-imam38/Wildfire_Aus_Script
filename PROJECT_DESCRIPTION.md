# Ignis-Twin

**Autonomous Multi-Modal Wildfire Digital Twin for Smoke-Agnostic Tracking**

---

## Situation

Extreme wildfires (for example Australia’s *Black Summer*) produce dense smoke plumes that block conventional optical satellites. That creates a **data blackout** for emergency operations and for keeping a Digital Twin aligned with the real fire.

## Task

Deliver a **fault-tolerant, automated pipeline** that can track fire fronts when optical views are unusable, by combining **thermal anomaly detections**, **Synthetic Aperture Radar (SAR)**, and **near–real-time meteorology**.

## Action (technical implementation)

| Area | What we built |
|------|----------------|
| **Resilient engineering** | A modular Python **orchestrator** with **exponential backoff and retries** so flaky satellite and HTTP APIs do not stop the run. |
| **Multi-modal fusion** | **NASA FIRMS** (thermal hotspots) paired with **Sentinel-1** SAR via **log-ratio change detection**, \(\ln(VV_{\mathrm{post}} / VV_{\mathrm{pre}})\), to support interpretation when smoke obscures optical imagery. |
| **Spatial intelligence** | Automated workflow from **discrete hotspot points** to **alpha-shape (concave hull) perimeters**, with metric work in **UTM zone 55S** where appropriate. |
| **Predictive loop** | **Open-Meteo** wind fields for situational vectors, plus a **closed-loop validation** step using **IoU (Intersection over Union)** against a later observation or reference geometry. |

## Result (novelty and outcomes)

- **Operational continuity:** Later phases can still run when earlier network or data steps partially fail, improving robustness for automated workflows.
- **Smoke-agnostic sensing:** SAR-backed change information complements thermal detections where **optical sensors would see little or nothing** through smoke.
- **Quantifiable accuracy:** The twin can **report its own geometric agreement** (e.g. IoU) with held-out or future perimeter data, supporting a self-measured notion of prediction error.

---

*For environment setup, dependencies, and how to run the pipeline and dashboard, see [README.md](README.md).*
