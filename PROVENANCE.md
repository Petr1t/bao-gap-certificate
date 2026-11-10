# Provenance

This repository is an extract. Every file below either comes verbatim from an
internal research repository, or was written for this extract. All extracted
files come from the same commit of that repository; its identifier is not
published, and the verifier is pinned by its SHA-256 instead:

* source repository: internal research repository (private)
* source subtree: `exploration/wetten/cpsat-zertifikate-strahlentherapie/` and `tests/`
* extracted: 2026-09-21

## Extracted files

| File here | Source path | Change |
|---|---|---|
| `portpy_cohort_check.py` | `exploration/wetten/cpsat-zertifikate-strahlentherapie/laeufe/checker/portpy_cohort_check.py` | unchanged (byte-identical, SHA-256 `32ee9e6a1e01859abf79853b31a4a8c0593bc40490429a85a1f71dae36e70cd2`) |
| `tests/test_portpy_cohort_check.py` | `tests/test_portpy_cohort_check.py` | decoupled, see below |

Everything else (`README.md`, `PROVENANCE.md`, `AGENTS.md`, `LICENSE`,
`.gitignore`, `pyproject.toml`, `examples/build_synthetic_example.py`) was
written for this repository.

### Decoupling of `tests/test_portpy_cohort_check.py`

Three changes, all of them removals or path repointing. No assertion was
weakened, added or rewritten.

1. The module path constant was repointed from
   `parents[1] / 'exploration/wetten/.../laeufe/checker/portpy_cohort_check.py'`
   to `parents[1] / 'portpy_cohort_check.py'`, matching this layout.
2. Removed the helper `_producer_modules` and the two tests that use it
   (`test_producer_full_chain_independent_source_and_primal_repair`,
   `test_producer_exact_arithmetic_against_independent_scalar_fractions`).
   They import the producer/solver package `portpy_cohort`, which is study
   orchestration and is not part of this extract.
3. Removed the six `test_acceptance_*` / `test_search_pilot_*` tests. They
   import `portpy_cohort_acceptance`, the study's admission gate, which is
   coupled to the machine it runs on: absolute local paths, backup receipts
   and a remote login to an off-site storage account.

14 of the original 22 tests remain — all of those that exercise the verifier
itself, including the fail-closed mutant batteries.

### `examples/build_synthetic_example.py`

Written for this repository. Its two-voxel, 72-beam geometry is derived from
the `model` fixture of the upstream test file (same source commit); the
certificate values it writes were chosen and hand-derived for this extract so
that the example shows both a zero and a nonzero endpoint. It carries no data
of any kind from the study.

## Deliberately not extracted

| Upstream | Why not |
|---|---|
| `laeufe/solver/portpy_cohort/` (producer: `runner.py`, `model.py`, `numerics.py`, `archive.py`, `bootstrap.py`, `search.py`, …) | study orchestration; the verifier imports none of it, by design |
| `laeufe/checker/portpy_cohort_acceptance.py` | admission gate; machine-specific paths, backup receipts, a remote storage account |
| `tests/test_portpy_cohort_safety.py` | tests of the producer, backups and cleanup gates |
| `laeufe/checker/benders_*.c`, the exhaustive enumerator | proves optimality over beam selections; a separate program, see the limits in the README |
| any model packet, certificate, cohort result or patient-derived artifact | patient data and unpublished results |

## Review status of the extracted code

* `portpy_cohort_check.py` is the verifier the study runs. It is written to
  import no producer code, and the study's admission gate refuses to run
  without a separate independent review attestation (`review.json`, binding a
  clean commit, a review log and a positive JUnit report). **That attestation
  is internal and is not published**, so this repository on its own does not
  evidence that the review happened. The claim made here is limited to what
  can be checked from the code: it imports no producer code.
* Parts of the upstream subtree carried a work-in-progress or unreviewed
  status at extraction time (a stage-1 pipeline on an unmerged branch, a
  per-patient report export merged without review). None of them is extracted
  here, and none of them is in the verifier's code path.
* The verifier's own scope limits are stated in its docstrings and repeated in
  the README: `verify_search_cuts` reports `optimality_verified: false`, and
  hash bracketing detects change during verification but does not attest where
  the bytes came from.

## Licensing of third-party parts

No third-party code and no third-party data is redistributed in this
repository. The entries below record the licence situation of the upstream
projects the research model relates to, for anyone reproducing the study.

| Part | Licence | Primary source | Retrieved |
|---|---|---|---|
| PortPy (toolkit and dataset the study's source data comes from) | "Apache License, Version 2.0 with the Commons Clause restriction" (verbatim from `LICENSE.txt`); the GitHub API reports the repository licence as `NOASSERTION` | <https://raw.githubusercontent.com/PortPy-Project/PortPy/master/LICENSE.txt> | 2026-09-21 |
| CORT dataset (Craft, Bangert, Long, Papp, Unkelbach, *Shared data for intensity modulated radiation therapy (IMRT) optimization research: the CORT dataset*, GigaScience 2014, 3:37) | the **article** is Open Access under CC-BY 4.0; the **dataset** (GigaDB, DOI 10.5524/100110) is under "Creative Commons Zero v1.0 Universal" (`cc0-1.0`), verbatim from its DataCite record | article: <https://academic.oup.com/gigascience/article/3/1/2047-217X-3-37/2682969>; dataset: <https://api.datacite.org/dois/10.5524/100110> | article 2026-09-21, dataset 2026-11-10 |

The GigaDB landing page renders its metadata in JavaScript; neither
`gigadb.org/dataset/100110` nor `gigadb.org/api/dataset/100110` returned a
licence string. The DataCite record of the dataset DOI states the licence
(see the table), and the article's own CC-BY notice governs the article only.

PortPy's Commons Clause is not engaged by this repository: it contains no
PortPy code and no PortPy data. The synthetic example is generated from
scratch and carries no data from PortPy or from the study.

This repository's own code is under the MIT licence in `LICENSE`
(copyright holder Petrit Isufi).
