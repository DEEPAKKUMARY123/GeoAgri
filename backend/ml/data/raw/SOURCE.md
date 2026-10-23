# Legacy Raw Datasets (Baseline / Prototype)

- **Directory**: `backend/ml/data/raw/`
- **Files**:
  - `Crop_recommendation.csv` (2,200 rows, 8 columns: N, P, K, temperature, humidity, ph, rainfall, label)
  - `Crop_recommendation_with_intercrops.csv` (synthetic combinations and companion crops)
  - `Crop_yield.csv` (Crop yield records across Indian states)
- **Provenance**: Unknown public web repository (Kaggle Indian Crop Datasets).
- **Quality / Agronomic Audit Status**:
  - Contains agronomically implausible outliers (e.g. `rice, 14.9 t/ha, humidity 32%` in `Crop_yield.csv`).
  - Lacks official government or FAO gazette citation.
- **Classification in GeoAgri**:
  - Demoted to **demo / baseline reference** only.
  - Production ML models are gated and being retrained on verified sources (FAOSTAT QCL, APY India, ICRISAT VDSA, ECOCROP envelopes, Soil Health Card statistics) per PRD §6.5 & §10.
- **Licence**: Unspecified public domain / CC0 equivalent assumed from source Kaggle repository.
- **Retrieved**: Prototype phase (~2024–2026).
