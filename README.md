# BAO gap certificate verifier

An independent, fail-closed verifier for exact rational optimality-gap
certificates of a beam-angle/fluence research model in radiotherapy planning.

Given a *model* (a hash-sealed directory of dose-influence coefficients) and a
*certificate* (`certificate.json`), the verifier recomputes both sides of the
bracket in exact arithmetic and reports the resulting gap. It imports no
producer code: everything it checks, it recomputes from the sealed bytes.

**This is a research model. Nothing here is a clinical statement, a treatment
plan, or a claim about patient benefit.**

## What the certificate asserts

For a fixed linear program over beamlet intensities `x`

```
minimize    c^T x
subject to  A x >= 1          (every target voxel receives at least the prescribed dose)
            0 <= x <= xmax
```

the certificate carries two exact rational numbers and the witnesses for both:

* **L — a lower bound**, from a dual vector `lambda >= 0` over the target rows.
  The verifier recomputes
  `L = sum(lambda) - xmax * sum_j max(0, (A^T lambda - c)_j)`
  over *every* beamlet of *every* beam, from the sealed coefficients. By weak
  duality of the bounded LP this is a valid lower bound on the optimum for any
  beam selection. The value stated in the certificate must match the recomputed
  one exactly; there is no tolerance.
* **U — an upper bound**, from a primal plan `x` on a named beam support. The
  verifier recomputes the dose `A x` and requires `A x >= 1` in exact rationals,
  requires `0 <= x <= xmax`, and recomputes `c^T x`. An upper bound is therefore
  only accepted if the plan really is feasible in the model.
* **The endpoint** is `100 * (U / L - 1)`, an upper bound on relative
  suboptimality of that plan within this model, reported per beam support
  (`planner` and `raster`). It is **not** a clinical benefit, a dose metric, or
  a comparison against any clinical plan.

Because `L` is computed over all beams and does not depend on the beam
selection, the same `L` bounds every selection of the same model — which is
what makes the two numbers comparable at all.

## Verifying a certificate

One command:

```
python portpy_cohort_check.py --model MODEL_DIR \
                              --certificate MODEL_DIR/certificate.json \
                              --report report.json
```

Exit status `0` means every check passed; `1` means it did not, and
`report.json` names the first failure. There is no partial success: any
malformed field, any hash that moves during verification, any infeasible dose
and any mismatching value aborts the run.

`--source ORIGINAL_DATA_DIR` additionally rederives the model from the original
dataset files: it re-reads the voxel map and the structure masks, rebuilds the
structure index sets, recomputes every cost coefficient from the untruncated
influence matrices in exact arithmetic, and compares the target rows byte for
byte. Without `--source` the verification proves the archived model; with it,
the model's derivation from the pinned original data.

`--search-cuts EVIDENCE_JSON` re-derives rounded Benders cuts from raw dual
vectors and binds a feasible witness. Read the limits below before reading
anything into its output.

### A runnable example, without patient data

```
python examples/build_synthetic_example.py --out example
python portpy_cohort_check.py --model example/model \
                              --source example/source \
                              --certificate example/model/certificate.json \
                              --report example/report.json
```

The generator writes a synthetic two-voxel, 72-beam instance (about 1.3 MB,
225 files) in exactly the layout of a real packet, together with a certificate
whose values are derived by hand in the generator's docstring. The report ends
with `"gap_percent": {"planner": "0", "raster": "50"}`: a tight lower bound, one
optimal plan and one deliberately wasteful plan, so both a zero and a nonzero
endpoint are exercised. Every influence coefficient is `1`; the instance carries
no anatomy and no clinical information.

## Model assumptions

These are the assumptions of the research model this verifier enforces, not
properties of any planning system:

| | |
|---|---|
| Target constraint | `A x >= 1`, one row per target (`PTV`) voxel, relative prescribed dose |
| Objective | `c_j = sum_S theta_S * mean_{v in S} A_vj` — a weighted sum of **flat, unweighted voxel means** per structure |
| Structure weights `theta` | `RECTUM` 1, `BLADDER` 3/5, `BODY` 3/5 (exact rationals; 3/5 is never a decimal) |
| Beamlet upper bound | `xmax = 1000` |
| Beams | 72 coplanar candidate beams, gantry `0, 5, ..., 355` degrees, couch and collimator 0 |
| Influences | the original untruncated full influence matrices, not a sparsity-thresholded variant |
| Arithmetic | `fractions.Fraction` throughout; IEEE inputs are expanded to exact dyadic rationals, never rounded |

The manifest is rejected unless it states exactly these values, so a packet
built under a different model cannot be verified by accident.

## Limits

* **Research model, not a clinic.** Flat voxel means are not a clinical
  objective; there are no DVH constraints, no fractionation, no normal-tissue
  complication model, no robustness, no deliverability, no MLC sequencing. The
  endpoint says how far a plan is from the optimum **of this LP**, nothing more.
* **The gap is a bound, not the gap.** `100*(U/L-1)` is an upper bound on
  relative suboptimality. A large value can mean a bad plan or a weak dual.
* **No optimality over beam selections.** `verify_search_cuts` binds rounded
  Benders cuts to raw dual vectors and checks a feasible witness. It explicitly
  reports `optimality_verified: false`. Proving that no other beam selection is
  better requires an exhaustive integer enumeration over those cut bytes, which
  is a separate program and is **not part of this repository**.
* **Hashes bracket reads, they do not attest events.** The verifier hashes its
  inputs before and after every read, so a file changed mid-run is caught. It
  cannot tell you where those bytes came from; that is what `--source` is for.
* **Scope of what has been checked.** The verifier was written to import no
  producer code, and the study that uses it admits a run only against an
  independent review attestation. That attestation, the study's orchestration,
  its acceptance gate, its backups and its results are not in this repository.
  No cohort numbers are published here.
* **Provenance and review status of the extracted files** are recorded in
  [PROVENANCE.md](PROVENANCE.md), including which upstream parts were still
  work in progress or unreviewed at the time of extraction.

## Requirements

Python 3.12 or newer, `h5py` and `numpy` (see `pyproject.toml`). The verifier
runs single-threaded and needs no solver, no network and no accelerator.
