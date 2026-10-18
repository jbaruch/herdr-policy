# Report classifier calibration

Calibration is a development procedure in a complete Herdr source checkout.
The installed classifier retains its prompt, questions, native envelope decoder
and TypeSafe client. Corpus evaluation, band scoring and synthetic-report
generation live under `scripts/report-calibration/`, excluded from both plugin
distributions. They propose changes; they do not modify live gate records or
accept a report.

The live bands are constants in `skills/herdr-foreman/foreman/report_gates.py`.
`BANDS_VERSION` identifies their reviewed calibration. Recalibrate after every
`JEV_MODEL` bump and question change.

1. Configure `TYPESAFE_API_KEY` as documented in `.env.example`.
2. Inspect the selected corpus without model calls:
   `bash scripts/report-calibration/evaluate.sh --corpus-only`.
3. Run `bash scripts/report-calibration/evaluate.sh --agent jev --results /private/labels.json`.
   Each selected report consumes one model call. Use `--limit N` for a bounded
   evaluation; keep labels and report contents outside the repository.
4. Run `python3 scripts/report-calibration/scoring.py calibrate /private/labels.json`.
   It prints proposed bands and selection counts, and writes nothing. It refuses
   a proposal with too few held-out labels. Selection rules and minimum counts
   live in that source module's docstring and constants.
5. Submit changes to the bands and `BANDS_VERSION` through a reviewed PR, with
   proposal counts and resulting false-gate counts in the changelog.

`--fixtures` generates synthetic reports in private scratch for the evaluation
and reports their results separately. It does not turn them into observed work.
The classifier and scoring regression suites stub model/vendor calls and spend
no model quota.
