# Campus outbreak data

Current control calibration uses UW–Madison W1 exclusively; see
[UW control integration](../docs/uw_control_integration.md). Notre Dame files
below are retained for historical reproduction.

## Historical Notre Dame outbreak reconstruction

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
  pre-major-mitigation window retained only for historical reproduction; current calibration uses UW W1.
- `notre_dame_2020_campus.csv` extends the aggregate sequence for diagnostic
  and counterfactual visualization.

The daily fields were reconstructed from the public report and related public
university summaries. In particular, the daily testing series should be treated
as a modelling input reconstructed at aggregate level, not as an official raw
administrative extract. The historical paper calibration used only the early window to
reduce confounding from the online-teaching and intensified-testing response.

## UW–Madison 2020 E0 calibration table

`uw_madison_2020_w1.csv` is a derived table, not a new source. It selects the
published on-campus testing series for 2020-08-17 through 2020-09-06 and pivots
it to one row per day:

```text
date,student_positive_tests,student_tests,employee_positive_tests,employee_tests
```

- 21 contiguous days; 589 positives and 18,314 tests in total.
- Students: 584 positives / 16,677 tests; employees: 5 / 1,637.
- Counts are by the dashboard receipt date, cover on-campus testing only, and
  assume the 2020-09-16 90-day repeat-positive exclusion applies to the whole
  published series.
- Zero-test days stay zero; no imputation, forward fill, or cumulative
  differencing is applied.
- `uw_madison_2020_w1.provenance.json` records the source dataset hash, filters,
  totals, assumptions, and the derived-file hash.

Rebuild both the W1 table and the 35-day W2/W3 table (2020-09-26 through
2020-10-30) with:

```powershell
& 'E:/pytroch/anaconda3/envs/simulation/python.exe' -m tools.build_uw_e0_data --force
```

The E0 study reads the W1 table only; the W2/W3 table is retained for the
optional later holdout and is not part of the current fit.
