# Xert Beta Preview bundle review — 2026-09-15

## Version and scope

Live authenticated Preview discovery returned
`https://beta.xertonline.com/js/svelte.js?id=b64f81bd74c9409cc62f90195453e8c3`,
with HTTP Last-Modified `Sat, 12 Sep 2026 12:11:28 GMT`.

- Previous pin: `87f393f744cd3cbc2ffb1a1db51ed33d15f79f888995cb4a72eef6c60d207a11`.
- Reviewed pin: `343a6527f8f12cc4eb9428e293895b767b6a54df6c1dd73810cc635298efddf9`.
- The previous bundle was not available locally: no numerical old/new model
  comparison is claimed.

The factory changed from minified `Tte` to `Module`, with `import_meta` as its
URL context. The adapter now mirrors current frontend signature rounding,
clamps, defaults and model-option defaults, and merges the WASM-returned
signature as the frontend does. It preserves explicit false/zero options.
Both loading and execution reject unreviewed hashes.

## Verification

An independent reference runner used the reviewed bundle's original
`initSigDisplay`, `buildEditedSignature` and the calculation portion of
`processRecordsForChart`, plus its original WASM factory. It stopped immediately
after `mpaChartData` and returned raw results. It did not use the adapter's
parameter normalization. Display units were g/h and metric.

All raw model outputs, signature fields and options matched exactly in all five
cases, including every time-series sample. This is code-path parity, not a
visual browser check or independent physiological validation.

| Case | Samples | Beta XSS | Peak modeled lactate (mmol/l) | Minimum glycogen (g) |
| --- | ---: | ---: | ---: | ---: |
| Moss–Horten, activity `4tpjg8fvkrqa5jre` | 22,438 | 310.456117 | 4.803736 | 93.903191 |
| 90 min at 205 W | 5,400 | 87.106300 | 0.369565 | 361.268025 |
| 6 × 3 min at 350 W, 3 min at 120 W after each | 3,360 | 61.412149 | 5.613303 | 352.832138 |
| 5 h at 260 W | 18,000 | 404.650645 | 1.725948 | 98.053185 |
| 1 h at 260 W + 1 h at 0 W | 7,200 | 79.106159 | 1.448633 | 359.812514 |

The interval case includes 10 min at 150 W first and 10 min at 120 W last.
Synthetic cases use the same activity-derived Beta signature: rounded TP
311 W, HIE 14.386 kJ, PP 780.2 W, glycogen capacity 480 g and MGUR 60 g/h.
Inputs use 5-second chart averaging and the activity's model options.
All normalized summaries serialized with nonfinite numbers prohibited.

`python3 -m unittest discover -s tests -p 'test_xert*.py'` passed 151 tests.
Regression coverage includes the hash guard, new factory execution,
signature rounding/clamping, option defaults, zero/false preservation and
returned-signature propagation. Plugin validation and `git diff --check` passed.

Installed plugin version `0.1.0+codex.20260915202215` was read back byte-for-byte
against the reviewed adapter. A fresh authenticated activity-preview call
through that installed module returned the reviewed hash and the same
310.45611659303233 Beta XSS.

Temporary reference runner and full verification data are under
`/private/tmp/xert-bundle-review/`; these are disposable local evidence, not
committed fixtures or a retained authenticated HTML/token snapshot.

No remote activities, signatures, options or workouts were changed. Beta XSS
remains separate from standard Xert XSS. These probes do not establish that
earlier long-ride model failures are fixed for all activities.
