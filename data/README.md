# Notre Dame outbreak reconstruction

The CSV files in this directory are compact, aggregate time series reconstructed
for model calibration. They do not contain individual-level records or direct
identifiers.

## Primary public source

Fox MD, Bailey DC, Seamon MD, and Miranda ML. "Response to a COVID-19
Outbreak on a University Campus -- Indiana, August 2020." *MMWR Morbidity and
Mortality Weekly Report* 70(4), 118-122 (2021).
DOI: 10.15585/mmwr.mm7004a3
https://www.cdc.gov/mmwr/volumes/70/wr/mm7004a3.htm

## Files and use

- `notre_dame_2020_early.csv` contains the 2020-08-03 through 2020-08-18
  pre-major-mitigation window used for parameter calibration.
- `notre_dame_2020_campus.csv` extends the aggregate sequence for diagnostic
  and counterfactual visualization.

The daily fields were reconstructed from the public report and related public
university summaries. In particular, the daily testing series should be treated
as a modelling input reconstructed at aggregate level, not as an official raw
administrative extract. The paper calibration uses only the early window to
reduce confounding from the online-teaching and intensified-testing response.
