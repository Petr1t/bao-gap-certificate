#!/usr/bin/env python3
"""Independent PortPy model/source and exact LP-certificate verifier.

No producer code is imported. Offline verification proves the archived model;
--source additionally rederives that model from the hash-bound original data.
Inputs must remain immutable throughout verification (hashes bracket reads).
"""
import argparse
import hashlib
import json
import math
import re
from fractions import Fraction
from pathlib import Path

import h5py
import numpy as np


class VerificationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(4 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _pairs(items):
    d = {}
    for k, v in items:
        require(k not in d, 'duplicate JSON key')
        d[k] = v
    return d


def read_json(path):
    def bad(value):
        raise VerificationError('nonfinite JSON value: ' + value)
    with open(path, encoding='utf-8') as f:
        return json.load(f, object_pairs_hook=_pairs, parse_constant=bad,
                         parse_float=lambda x: _finite_float(x))


def _finite_float(text):
    value = float(text)
    require(math.isfinite(value), 'nonfinite JSON number')
    return value


def integer(x, minimum=0):
    require(type(x) is int and x >= minimum, 'invalid integer')
    return x


def rational(x):
    require(type(x) is str and re.fullmatch(r'-?(0|[1-9][0-9]*)(/[1-9][0-9]*)?', x),
            'invalid rational string')
    q = Fraction(x)
    require(str(q) == x, 'noncanonical rational')
    return q


def safe(root, name):
    require(type(name) is str and re.fullmatch(r'[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*', name)
            and all(p not in ('.', '..') for p in name.split('/')), 'unsafe path')
    p = Path(root) / name
    require(p.resolve().is_relative_to(Path(root).resolve()) and not p.is_symlink(), 'unsafe link')
    return p


def digest(x):
    require(type(x) is str and re.fullmatch('[0-9a-f]{64}', x), 'invalid digest')
    return x


def indices(x, n):
    require(type(x) is list and bool(x), 'empty/malformed indices')
    for v in x:
        require(integer(v) < n, 'index out of bounds')
    require(x == sorted(set(x)), 'indices not sorted and unique')


def _manifest(root):
    m = read_json(Path(root) / 'model.json')
    require(type(m) is dict and type(m.get('schema')) is int and m['schema'] == 1, 'schema')
    require(type(m.get('patient')) is str and re.fullmatch(r'Prostate_Patient_[1-9][0-9]*', m['patient']), 'patient')
    require(1 <= int(m['patient'].rsplit('_', 1)[1]) <= 129, 'patient out of cohort range')
    require(type(m.get('revision')) is str and re.fullmatch('[0-9a-f]{40}', m['revision']), 'revision')
    expected = {'xmax': 1000, 'target': 'PTV', 'weights': {'RECTUM': '1', 'BLADDER': '3/5', 'BODY': '3/5'},
                'normalization': 'Ax>=1', 'mean': 'flat-dose-voxel'}
    require(m.get('model') == expected and type(m['model']['xmax']) is int, 'model specification')
    n = integer(m['n_voxels'], 1)
    require(set(m['structures']) == {'PTV', 'RECTUM', 'BLADDER', 'BODY'}, 'structures')
    for ids in m['structures'].values():
        indices(ids, n)
    require(m['ptv_indices'] == m['structures']['PTV'], 'PTV mapping')
    indices(m['ptv_indices'], n)
    beams = m['beams']
    require(type(beams) is list and len(beams) == 72, '72 beams required')
    ids, names = set(), set()
    for k, b in enumerate(beams):
        bid = integer(b['id'])
        require(bid not in ids, 'duplicate beam id')
        ids.add(bid)
        require(integer(b['gantry']) == k * 5 and integer(b['couch']) == 0 and integer(b['collimator']) == 0, 'beam angles')
        integer(b['columns'], 1)
        require(type(b['file']) is str and re.fullmatch(r'beam-[0-9]{3,}\.h5', b['file']) and b['file'] not in names, 'beam filename')
        names.add(b['file'])
        digest(b['sha256'])
    p = m['planner_ids']
    require(type(p) is list and len(p) == 9, 'planner cardinality')
    for v in p:
        integer(v)
    require(len(set(p)) == 9 and set(p) <= ids, 'planner support')
    require(type(m['source_files']) is dict and bool(m['source_files']), 'source manifest')
    for name, h in m['source_files'].items():
        safe(root, name)
        digest(h)
    return m


def _dataset(f, name):
    require(isinstance(f.get(name, getlink=True), h5py.HardLink), 'HDF5 dataset link')
    ds = f[name]
    _local_dataset(ds)
    return ds


def _local_dataset(ds):
    require(isinstance(ds, h5py.Dataset) and not ds.is_virtual and not ds.external, 'external/virtual HDF5 dataset')
    require(isinstance(ds.parent.get(ds.name.rsplit('/', 1)[-1], getlink=True), h5py.HardLink), 'HDF5 dataset link')


def _matrix(ds, shape):
    _local_dataset(ds)
    require(isinstance(ds, h5py.Dataset) and ds.shape == shape and ds.dtype.kind == 'f'
            and ds.dtype.itemsize in (4, 8), 'matrix dimensions/dtype')


def _values(a):
    require(np.isfinite(a).all() and (a >= 0).all(), 'negative/nonfinite matrix')


def _costs(f, columns):
    for k in ('c_num', 'c_den'):
        _dataset(f, k)
        require(isinstance(f[k], h5py.Dataset) and f[k].shape == (columns,)
                and h5py.check_string_dtype(f[k].dtype) is not None
                and h5py.check_string_dtype(f[k].dtype).encoding == 'utf-8', 'cost vector type/shape')
    nums, dens = f['c_num'].asstr()[:], f['c_den'].asstr()[:]
    out = []
    for n, d in zip(nums, dens):
        require(re.fullmatch('0|[1-9][0-9]*', n) and re.fullmatch('[1-9][0-9]*', d), 'cost integers')
        q = Fraction(int(n), int(d))
        require(q.numerator == int(n) and q.denominator == int(d), 'unreduced cost')
        out.append(q)
    return out


def _dyadic(a):
    """Represent a finite binary float array as integer array times 2**e."""
    mantissa, exponent = np.frexp(a)
    nz = a != 0
    if not nz.any():
        return np.zeros(a.shape, dtype=object), 0
    # 53 bits also represents every binary32 exactly. Python integers avoid overflow.
    exponent = exponent.astype(np.int64) - 53
    e = int(exponent[nz].min())
    integers = np.ldexp(mantissa, 53).astype(np.int64).astype(object)
    shifts = np.where(nz, exponent - e, 0)
    return integers * np.left_shift(np.ones(a.shape, dtype=object), shifts), e


def _scale(e):
    return Fraction(2 ** e) if e >= 0 else Fraction(1, 2 ** (-e))


def _exact_sums(a):
    """Exact nonnegative sums from IEEE bit fields, independent of frexp.

    Bincount sums 26/27-bit limbs exactly in binary64: at most 2**24
    rows per slab keeps every intermediate integer strictly below 2**53.
    Only the final exponent buckets need Python's arbitrary-size integers.
    """
    _values(a)
    result = [Fraction(0) for _ in range(a.shape[1])]
    for start in range(0, a.shape[0], 1 << 24):
        for col in range(a.shape[1]):
            bits = np.asarray(a[start:start+(1 << 24), col], dtype=np.float64).view(np.uint64)
            raw_exp = ((bits >> 52) & 2047).astype(np.int64)
            mantissa = bits & ((1 << 52) - 1)
            mantissa = mantissa | np.where(raw_exp != 0, np.uint64(1 << 52), np.uint64(0))
            bucket = np.maximum(raw_exp - 1, 0)
            low = np.bincount(bucket, weights=(mantissa & ((1 << 26) - 1)).astype(np.float64), minlength=2046)
            high = np.bincount(bucket, weights=(mantissa >> 26).astype(np.float64), minlength=2046)
            for i in np.flatnonzero((low != 0) | (high != 0)):
                total = int(low[i]) + (int(high[i]) << 26)
                result[col] += total * _scale(int(i) - 1074)
    return result


def _common(q):
    denominator = math.lcm(*(x.denominator for x in q))
    return np.array([x.numerator * (denominator // x.denominator) for x in q], dtype=object), denominator


def _weighted(a, weights, denominator, transpose=False):
    """Exact matvec after removing only algebraically zero weights.

    Integer weights share the positive denominator from _common. All nonzero
    weights, including arbitrarily tiny rationals, remain in the computation.
    Validate the full input matrix before calling this internal arithmetic helper.
    """
    active = weights != 0
    output_size = a.shape[1] if transpose else a.shape[0]
    if not active.any():
        return [Fraction(0)] * output_size
    reduced = a[active, :] if transpose else a[:, active]
    integers, exponent = _dyadic(reduced)
    products = weights[active] @ integers if transpose else integers @ weights[active]
    scale = _scale(exponent) / denominator
    return [int(value) * scale for value in products]


def _block_width(ds):
    # Keep full-source blocks <=64 MiB, aligned to on-disk column chunks if possible.
    limit = max(1, min(64, (64 << 20) // max(1, ds.shape[0] * ds.dtype.itemsize)))
    width = ds.chunks[1] if ds.chunks else 1
    return max(width, limit // width * width) if width <= limit else limit


def _source_masks(source, m):
    vm = read_json(source / 'OptimizationVoxels_MetaData.json')
    require(vm.get('ct_to_dose_voxel_map_File') == 'OptimizationVoxels_Data.h5/ct_to_dose_voxel_map', 'voxel reference')
    sm = read_json(source / 'StructureSet_MetaData.json')
    require(type(sm) is list, 'structure metadata')
    refs = {}
    for row in sm:
        require(type(row) is dict and type(row.get('name')) is str and row['name'] not in refs, 'structure metadata duplicate/name')
        refs[row['name']] = row.get('structure_mask_3d_File')
    for name in m['structures']:
        require(refs.get(name) == f'StructureSet_Data.h5/{name}', 'structure reference')
    with h5py.File(source / 'OptimizationVoxels_Data.h5', 'r') as vf, h5py.File(source / 'StructureSet_Data.h5', 'r') as sf:
        mapping = _dataset(vf, 'ct_to_dose_voxel_map')
        _local_dataset(mapping)
        require(mapping.ndim == 3 and all(mapping.shape) and mapping.dtype.kind in 'iu', 'voxel map type')
        seen = {name: np.zeros(m['n_voxels'], dtype=bool) for name in m['structures']}
        for name in seen:
            _dataset(sf, name)
            require(sf[name].shape == mapping.shape and sf[name].dtype.kind in 'biuf', 'mask type/shape')
        for start in range(mapping.shape[0]):
            values = mapping[start]
            require((values >= -1).all() and (values < m['n_voxels']).all(), 'voxel map range')
            for name, membership in seen.items():
                mask = sf[name][start]
                require(np.isfinite(mask).all() and ((mask == 0) | (mask == 1)).all(), 'nonbinary mask')
                selected = values[(mask != 0) & (values >= 0)]
                membership[selected] = True
        for name, selected in seen.items():
            require(np.flatnonzero(selected).tolist() == m['structures'][name], 'source structure mismatch: ' + name)


def _required_sources(m):
    files = {'CT_MetaData.json', 'OptimizationVoxels_Data.h5', 'OptimizationVoxels_MetaData.json', 'StructureSet_Data.h5',
             'StructureSet_MetaData.json', 'PlannerBeams.json'}
    for b in m['beams']:
        files.update({f"Beams/Beam_{b['id']}_MetaData.json", f"Beams/Beam_{b['id']}_Data.h5"})
    return files


def verify_model(model_dir, source=None):
    root = Path(model_dir)
    before = sha(root / 'model.json')
    m = _manifest(root)
    require(_required_sources(m) <= set(m['source_files']), 'missing source binding')
    source = Path(source) if source is not None else None
    if source is not None:
        for name, h in m['source_files'].items():
            require(sha(safe(source, name)) == h, 'source hash mismatch: ' + name)
        _source_masks(source, m)
        planner = read_json(source / 'PlannerBeams.json')['IDs']
        require(type(planner) is list and all(type(v) is int for v in planner)
                and len(planner) == 9 and set(planner) == set(m['planner_ids']), 'source planner mismatch')
    for b in m['beams']:
        path = safe(root, b['file'])
        require(sha(path) == b['sha256'], 'model beam hash')
        with h5py.File(path, 'r') as f:
            _matrix(_dataset(f, 'A'), (len(m['ptv_indices']), b['columns']))
            costs = _costs(f, b['columns'])
            for j in range(0, b['columns'], 32):
                _values(f['A'][:, j:j+32])
            if source is not None:
                meta = read_json(source / f"Beams/Beam_{b['id']}_MetaData.json")
                require(type(meta.get('ID')) is int and meta['ID'] == b['id'], 'source beam id')
                for key, field in [('gantry_angle', 'gantry'), ('couch_angle', 'couch'), ('collimator_angle', 'collimator')]:
                    require(type(meta.get(key)) in (int, float) and meta[key] == b[field], 'source beam angle')
                require(meta.get('influenceMatrixFull_File') == f"Beam_{b['id']}_Data.h5/inf_matrix_full", 'full matrix reference')
                with h5py.File(source / f"Beams/Beam_{b['id']}_Data.h5", 'r') as raw:
                    ds = _dataset(raw, 'inf_matrix_full')
                    _matrix(ds, (m['n_voxels'], b['columns']))
                    require(ds.dtype == f['A'].dtype, 'original matrix dtype')
                    step = _block_width(ds)
                    for j in range(0, b['columns'], step):
                        full = ds[:, j:j+step]
                        _values(full)
                        require(np.array_equal(full[m['ptv_indices']], f['A'][:, j:j+step]), 'source PTV coefficients mismatch')
                        expected = [Fraction(0) for _ in range(full.shape[1])]
                        for name, weight in [('RECTUM', Fraction(1)), ('BLADDER', Fraction(3, 5)), ('BODY', Fraction(3, 5))]:
                            rows = m['structures'][name]
                            for k, value in enumerate(_exact_sums(full[rows])):
                                expected[k] += value * weight / len(rows)
                        require(expected == costs[j:j+step], 'source costs mismatch')
        require(sha(path) == b['sha256'], 'model beam changed during verification')
    if source is not None:
        for name, h in m['source_files'].items():
            require(sha(safe(source, name)) == h, 'source changed during verification: ' + name)
    require(sha(root / 'model.json') == before, 'model changed during verification')
    return {'ok': True, 'patient': m['patient'], 'model_sha256': before,
            'source_verified': source is not None}


def verify_certificate(model_dir, certificate_path):
    root = Path(model_dir)
    model_result = verify_model(root)
    m = _manifest(root)
    cert_hash = sha(certificate_path)
    cert = read_json(certificate_path)
    require(type(cert['schema']) is int and cert['schema'] == 1, 'certificate schema')
    require(cert['model_sha256'] == model_result['model_sha256'], 'certificate model binding')
    require(type(cert['lower']['lambda']) is list, 'dual vector type')
    lam = [rational(v) for v in cert['lower']['lambda']]
    require(len(lam) == len(m['ptv_indices']) and all(v >= 0 for v in lam), 'dual dimensions/sign')
    li, ld = _common(lam)
    lower = sum(lam, Fraction(0))
    upper = {}
    for name in ('planner', 'raster'):
        item = cert['upper'][name]
        ids = item['beam_ids']
        expected = set(m['planner_ids']) if name == 'planner' else {b['id'] for b in m['beams'] if b['gantry'] in range(0, 321, 40)}
        ordered = [b['id'] for b in m['beams'] if b['id'] in expected]
        require(type(ids) is list and all(type(v) is int for v in ids) and ids == ordered, 'upper beam support/order')
        require(type(item['x']) is list, 'primal vector type')
        x = [rational(v) for v in item['x']]
        require(len(x) == sum(b['columns'] for b in m['beams'] if b['id'] in expected)
                and all(0 <= v <= 1000 for v in x), 'primal bounds/dimensions')
        xi, xd = _common(x)
        upper[name] = {'ids': expected, 'x': x, 'xi': xi, 'xd': xd, 'offset': 0,
                       'dose': [Fraction(0)] * len(lam), 'value': Fraction(0)}
    for b in m['beams']:
        path = root / b['file']
        require(sha(path) == b['sha256'], 'certificate beam binding')
        with h5py.File(path, 'r') as f:
            costs = _costs(f, b['columns'])
            for j in range(0, b['columns'], 16):
                a = f['A'][:, j:j+16]
                _values(a)
                dual = _weighted(a, li, ld, transpose=True)
                for k, value in enumerate(dual):
                    lower -= 1000 * max(Fraction(0), value - costs[j+k])
                for state in upper.values():
                    if b['id'] not in state['ids']:
                        continue
                    start = state['offset'] + j
                    stop = start + a.shape[1]
                    dose = _weighted(a, state['xi'][start:stop], state['xd'])
                    for row, value in enumerate(dose):
                        state['dose'][row] += value
                    state['value'] += sum((q * c for q, c in zip(state['x'][start:stop], costs[j:j+a.shape[1]])), Fraction(0))
            for state in upper.values():
                if b['id'] in state['ids']:
                    state['offset'] += b['columns']
        require(sha(path) == b['sha256'], 'certificate beam changed')
    require(lower == rational(cert['lower']['value']), 'lower value mismatch')
    result = {'ok': True, 'model_sha256': model_result['model_sha256'], 'certificate_sha256': cert_hash, 'lower': str(lower), 'upper': {}, 'gap_percent': {}}
    for name, state in upper.items():
        require(all(v >= 1 for v in state['dose']), 'infeasible dose')
        value = state['value']
        require(value == rational(cert['upper'][name]['value']) and lower <= value, 'upper value mismatch')
        result['upper'][name] = str(value)
        result['gap_percent'][name] = str(100 * (value / lower - 1)) if lower > 0 else None
    require(sha(root / 'model.json') == model_result['model_sha256'] and sha(certificate_path) == cert_hash, 'certificate inputs changed')
    return result


def verify_search_cuts(model_dir, evidence_path):
    """Bind rounded Benders cuts and a feasible k=9 witness; NOT optimality.

    The exhaustive integer checker must separately verify the resulting bytes.
    Floor(C*2**q), ceil(mu*2**q) preserve a conservative lower cut.
    """
    root, evidence_path = Path(model_dir), Path(evidence_path)
    report = verify_model(root)
    m = _manifest(root)
    evidence_hash = sha(evidence_path)
    evidence = read_json(evidence_path)
    require(type(evidence['schema']) is int and evidence['schema'] == 1, 'search schema')
    require(evidence['model_sha256'] == report['model_sha256'], 'search model binding')
    require(type(evidence['q']) is int and evidence['q'] == 48, 'search quantization')
    require(evidence['cuts_file'] == 'cuts_exact.txt', 'search cuts filename')
    cuts_path = safe(evidence_path.parent, evidence['cuts_file'])
    cuts_hash = digest(evidence['cuts_sha256'])
    require(sha(cuts_path) == cuts_hash, 'search cuts hash')
    witness = evidence['witness']
    selected = witness['beam_ids']
    require(type(selected) is list and len(selected) == 9 and all(type(v) is int for v in selected), 'search witness support')
    ordered = [b['id'] for b in m['beams'] if b['id'] in selected]
    require(selected == ordered, 'search witness support/order')
    require(type(witness['x']) is list, 'search witness vector')
    x = [rational(v) for v in witness['x']]
    require(len(x) == sum(b['columns'] for b in m['beams'] if b['id'] in selected)
            and all(0 <= v <= 1000 for v in x), 'search witness bounds/dimensions')
    xi, xd = _common(x)
    require(type(evidence['cuts']) is list and bool(evidence['cuts']), 'empty search cuts')
    multipliers, constants = [], []
    for cut in evidence['cuts']:
        require(type(cut['lambda']) is list, 'search multiplier type')
        lam = [rational(v) for v in cut['lambda']]
        require(len(lam) == len(m['ptv_indices']) and all(v >= 0 for v in lam), 'search multiplier dimensions/sign')
        multipliers.append(_common(lam))
        constants.append(sum(lam, Fraction(0)))
    penalties = [[] for _ in multipliers]
    doses = [Fraction(0)] * len(m['ptv_indices'])
    value, offset = Fraction(0), 0
    for beam in m['beams']:
        path = root / beam['file']
        require(sha(path) == beam['sha256'], 'search beam binding')
        sums = [Fraction(0)] * len(multipliers)
        with h5py.File(path, 'r') as f:
            costs = _costs(f, beam['columns'])
            _matrix(_dataset(f, 'A'), (len(doses), beam['columns']))
            for j in range(0, beam['columns'], 16):
                a = f['A'][:, j:j+16]
                _values(a)
                for k, (li, ld) in enumerate(multipliers):
                    dual = _weighted(a, li, ld, transpose=True)
                    sums[k] += sum((max(Fraction(0), v - costs[j+c])
                                    for c, v in enumerate(dual)), Fraction(0))
                if beam['id'] in selected:
                    start, stop = offset+j, offset+j+a.shape[1]
                    addition = _weighted(a, xi[start:stop], xd)
                    for row, v in enumerate(addition):
                        doses[row] += v
                    value += sum((v*c for v, c in zip(x[start:stop], costs[j:j+a.shape[1]])), Fraction(0))
        if beam['id'] in selected:
            offset += beam['columns']
        for k, penalty in enumerate(sums):
            penalties[k].append(penalty)
        require(sha(path) == beam['sha256'], 'search beam changed')
    require(all(v >= 1 for v in doses), 'search witness infeasible dose')
    require(value == rational(witness['value']), 'search witness objective')
    unit = 1 << 48
    # Python's // is floor even for signed integers; penalties are nonnegative.
    def ceiling(q):
        return -((-q.numerator) // q.denominator)
    positions = [i for i, b in enumerate(m['beams']) if b['id'] in selected]
    header = [-1, 2, 1000, 48, ceiling(value*unit), 72, len(multipliers), *positions]
    lines = [' '.join(map(str, header))]
    lines.extend(str((v*unit).numerator // (v*unit).denominator) for v in constants)
    lines.extend(' '.join(str(ceiling(v*unit)) for v in row) for row in penalties)
    expected = ('\n'.join(lines) + '\n').encode('ascii')
    require(cuts_path.read_bytes() == expected, 'search rounded cuts differ from exact reconstruction')
    require(sha(root / 'model.json') == report['model_sha256'] and sha(evidence_path) == evidence_hash
            and sha(cuts_path) == cuts_hash, 'search inputs changed')
    return {'ok': True, 'cuts_verified': True, 'optimality_verified': False,
            'witness_value': str(value), 'model_sha256': report['model_sha256'],
            'cuts_sha256': cuts_hash, 'cut_count': len(multipliers)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--source')
    parser.add_argument('--certificate')
    parser.add_argument('--search-cuts')
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    try:
        result = verify_model(args.model, args.source)
        if args.certificate:
            result['certificate'] = verify_certificate(args.model, args.certificate)
        if args.search_cuts:
            result['search_cuts'] = verify_search_cuts(args.model, args.search_cuts)
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
        result = {'ok': False, 'error': str(exc)}
    Path(args.report).write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n')
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
