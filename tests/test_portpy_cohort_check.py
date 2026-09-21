"""Independent fixtures/mutants for the PortPy cohort verification core."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip('h5py')
PATH = Path(__file__).resolve().parents[1] / 'portpy_cohort_check.py'
spec = importlib.util.spec_from_file_location('cohort_check', PATH)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def dump(path, value):
    path.write_text(json.dumps(value))


@pytest.fixture
def model(tmp_path):
    root = tmp_path / 'model'
    source = tmp_path / 'source'
    root.mkdir()
    source.mkdir()
    (source / 'Beams').mkdir()
    dump(source / 'CT_MetaData.json', {'resolution_xyz_mm': [1, 1, 1]})
    with h5py.File(source / 'OptimizationVoxels_Data.h5', 'w') as f:
        f['ct_to_dose_voxel_map'] = np.array([[[-1, 0, 1]]], dtype=np.int64)
    with h5py.File(source / 'StructureSet_Data.h5', 'w') as f:
        f['PTV'] = np.array([[[0, 1, 0]]], dtype=np.uint8)
        for name in ['RECTUM', 'BLADDER', 'BODY']:
            f[name] = np.array([[[0, 0, 1]]], dtype=np.uint8)
    dump(source / 'OptimizationVoxels_MetaData.json', {'ct_to_dose_voxel_map_File': 'OptimizationVoxels_Data.h5/ct_to_dose_voxel_map'})
    dump(source / 'StructureSet_MetaData.json', [{'name': n, 'structure_mask_3d_File': f'StructureSet_Data.h5/{n}'} for n in ['PTV', 'RECTUM', 'BLADDER', 'BODY']])
    dump(source / 'PlannerBeams.json', {'IDs': list(range(9))})
    beams = []
    for i in range(72):
        filename = f'beam-{i:03}.h5'
        with h5py.File(root / filename, 'w') as f:
            f['A'] = np.ones((1, 1), dtype=np.float32)
            f.create_dataset('c_num', data=['11'], dtype=h5py.string_dtype('utf-8'))
            f.create_dataset('c_den', data=['5'], dtype=h5py.string_dtype('utf-8'))
        beams.append({'id': i, 'gantry': 5*i, 'couch': 0, 'collimator': 0, 'columns': 1, 'file': filename, 'sha256': check.sha(root / filename)})
        with h5py.File(source / f'Beams/Beam_{i}_Data.h5', 'w') as f:
            f['inf_matrix_full'] = np.ones((2, 1), dtype=np.float32)
        dump(source / f'Beams/Beam_{i}_MetaData.json', {'ID': i, 'gantry_angle': 5*i, 'couch_angle': 0, 'collimator_angle': 0, 'influenceMatrixFull_File': f'Beam_{i}_Data.h5/inf_matrix_full'})
    m = {'schema': 1, 'patient': 'Prostate_Patient_1', 'revision': 'a'*40,
         'model': {'xmax': 1000, 'target': 'PTV', 'weights': {'RECTUM': '1', 'BLADDER': '3/5', 'BODY': '3/5'}, 'normalization': 'Ax>=1', 'mean': 'flat-dose-voxel'},
         'n_voxels': 2, 'ptv_indices': [0], 'structures': {'PTV': [0], 'RECTUM': [1], 'BLADDER': [1], 'BODY': [1]},
         'planner_ids': list(range(9)), 'beams': beams,
         'source_files': {str(p.relative_to(source)): check.sha(p) for p in source.rglob('*') if p.is_file()}}
    dump(root / 'model.json', m)
    cert = {'schema': 1, 'model_sha256': check.sha(root / 'model.json'), 'lower': {'lambda': ['11/5'], 'value': '11/5'},
            'upper': {name: {'beam_ids': ids, 'x': ['1'] + ['0']*8, 'value': '11/5'} for name, ids in [('planner', list(range(9))), ('raster', list(range(0, 65, 8)))]}}
    dump(root / 'certificate.json', cert)
    return root, source, m, cert


def test_exact_source_offline_certificate_and_voxel_zero(model):
    root, source, _, _ = model
    assert check.verify_model(root, source)['source_verified']
    result = check.verify_certificate(root, root / 'certificate.json')
    assert result['certificate_sha256'] == check.sha(root / 'certificate.json')
    assert result['lower'] == '11/5'
    assert result['gap_percent'] == {'planner': '0', 'raster': '0'}


def test_source_changed_cost_even_with_rehashed_model_rejected(model):
    root, source, m, _ = model
    with h5py.File(root / 'beam-000.h5', 'r+') as f:
        f['c_num'][0] = '12'
    m['beams'][0]['sha256'] = check.sha(root / 'beam-000.h5')
    dump(root / 'model.json', m)
    with pytest.raises(check.VerificationError, match='source costs'):
        check.verify_model(root, source)


def test_source_changed_ptv_even_with_rehashed_model_rejected(model):
    root, source, m, _ = model
    with h5py.File(root / 'beam-000.h5', 'r+') as f:
        f['A'][0, 0] = 2
    m['beams'][0]['sha256'] = check.sha(root / 'beam-000.h5')
    dump(root / 'model.json', m)
    with pytest.raises(check.VerificationError, match='PTV coefficients'):
        check.verify_model(root, source)


def test_mutants_fail_closed(model):
    root, _, m, cert = model
    original = json.dumps(cert)
    for mutate in [lambda c: c.update(model_sha256='f'*64),
                   lambda c: c['lower'].update(value='0'),
                   lambda c: c['lower'].update(**{'lambda': ['-1']}),
                   lambda c: c['upper']['planner'].update(x=['1001']+['0']*8),
                   lambda c: c['upper']['planner'].update(x=['0']*9),
                   lambda c: c['upper']['planner'].update(beam_ids=list(range(1, 10))),
                   lambda c: c['upper']['planner'].update(value='22/10')]:
        changed = json.loads(original)
        mutate(changed)
        dump(root / 'certificate.json', changed)
        with pytest.raises(check.VerificationError):
            check.verify_certificate(root, root / 'certificate.json')
    for value in [float('nan'), -1.0, float('inf')]:
        with h5py.File(root / 'beam-000.h5', 'r+') as f:
            f['A'][0, 0] = value
        m['beams'][0]['sha256'] = check.sha(root / 'beam-000.h5')
        dump(root / 'model.json', m)
        with pytest.raises(check.VerificationError, match='negative/nonfinite'):
            check.verify_model(root)


def test_source_mask_binding_and_missing_source_hash(model):
    root, source, m, _ = model
    with h5py.File(source / 'StructureSet_Data.h5', 'r+') as f:
        f['PTV'][:] = [[[0, 0, 1]]]
    m['source_files']['StructureSet_Data.h5'] = check.sha(source / 'StructureSet_Data.h5')
    dump(root / 'model.json', m)
    with pytest.raises(check.VerificationError, match='structure mismatch'):
        check.verify_model(root, source)
    del m['source_files']['PlannerBeams.json']
    dump(root / 'model.json', m)
    with pytest.raises(check.VerificationError, match='missing source binding'):
        check.verify_model(root)


def test_strict_json_and_no_partial_beam_model(model):
    root, _, m, _ = model
    m['beams'].pop()
    dump(root / 'model.json', m)
    with pytest.raises(check.VerificationError, match='72 beams'):
        check.verify_model(root)
    for text in ['{"schema":1,"schema":1}', '{"schema":NaN}', '{} trailing']:
        (root / 'model.json').write_text(text)
        with pytest.raises(ValueError):
            check.verify_model(root)


def test_dyadic_exactness_extreme_and_subnormal():
    a = np.array([[np.nextafter(0.0, 1.0), 0.1], [1.0, 2.0]])
    from fractions import Fraction
    assert check._exact_sums(a) == [Fraction(float(a[0, 0])) + 1, Fraction(0.1) + 2]


def test_source_references_sentinel_and_dtype(model):
    root, source, m, _ = model
    meta = source / 'OptimizationVoxels_MetaData.json'
    dump(meta, {'ct_to_dose_voxel_map_File': 'wrong.h5/map'})
    m['source_files'][meta.name] = check.sha(meta)
    dump(root / 'model.json', m)
    with pytest.raises(check.VerificationError, match='voxel reference'):
        check.verify_model(root, source)
    dump(meta, {'ct_to_dose_voxel_map_File': 'OptimizationVoxels_Data.h5/ct_to_dose_voxel_map'})
    m['source_files'][meta.name] = check.sha(meta)
    with h5py.File(source / 'OptimizationVoxels_Data.h5', 'r+') as f:
        f['ct_to_dose_voxel_map'][0, 0, 0] = -2
    m['source_files']['OptimizationVoxels_Data.h5'] = check.sha(source / 'OptimizationVoxels_Data.h5')
    dump(root / 'model.json', m)
    with pytest.raises(check.VerificationError, match='voxel map range'):
        check.verify_model(root, source)


def test_cli_failure_exit_and_report(model, monkeypatch):
    import sys
    root, _, _, cert = model
    cert['lower']['value'] = '0'
    dump(root / 'certificate.json', cert)
    report = root / 'report.json'
    monkeypatch.setattr(sys, 'argv', [str(PATH), '--model', str(root), '--certificate', str(root / 'certificate.json'), '--report', str(report)])
    assert check.main() == 1
    assert json.loads(report.read_text())['ok'] is False


def test_hdf5_external_link_is_not_hash_bound(model):
    root, _, m, _ = model
    with h5py.File(root / 'beam-000.h5', 'r+') as f:
        del f['A']
        f['A'] = h5py.ExternalLink('beam-001.h5', '/A')
    m['beams'][0]['sha256'] = check.sha(root / 'beam-000.h5')
    dump(root / 'model.json', m)
    with pytest.raises(check.VerificationError, match='dataset link'):
        check.verify_model(root)


def test_ieee_bucket_sums_against_scalar_rationals():
    from fractions import Fraction
    rng = np.random.default_rng(71)
    a = np.ldexp(rng.random((100, 4)), rng.integers(-1070, 1000, (100, 4)))
    assert check._exact_sums(a) == [sum((Fraction(float(v)) for v in a[:, j]), Fraction(0)) for j in range(4)]


def test_patient_range_and_boolean_support_ids(model):
    root, _, m, _ = model
    for field, value in [('patient', 'Prostate_Patient_130'), ('planner_ids', [True]+list(range(1, 9)))]:
        changed = dict(m)
        changed[field] = value
        dump(root / 'model.json', changed)
        with pytest.raises(check.VerificationError):
            check.verify_model(root)
    m['beams'][0]['id'] = False
    dump(root / 'model.json', m)
    with pytest.raises(check.VerificationError):
        check.verify_model(root)


def test_search_cuts_exact_rounding_binding_and_mutants(model):
    root, _, _, _ = model
    # A=1, c=11/5: lambda=7/3 gives mu=2/15 per beam.
    # The independently written fixture exercises strict floor/ceiling, not only integers.
    unit = 1 << 48
    cuts = root / 'cuts_exact.txt'
    payload = ('-1 2 1000 48 ' + str((11*unit+4)//5) + ' 72 1 0 1 2 3 4 5 6 7 8\n'
               + str(7*unit//3) + '\n' + ' '.join([str((2*unit+14)//15)]*72) + '\n')
    cuts.write_text(payload)
    evidence = {'schema': 1, 'model_sha256': check.sha(root / 'model.json'),
                'witness': {'beam_ids': list(range(9)), 'x': ['1']+['0']*8, 'value': '11/5'},
                'cuts': [{'lambda': ['7/3']}], 'q': 48,
                'cuts_file': 'cuts_exact.txt', 'cuts_sha256': check.sha(cuts)}
    path = root / 'search.json'
    dump(path, evidence)
    result = check.verify_search_cuts(root, path)
    assert result['cuts_verified'] and not result['optimality_verified']
    assert result['witness_value'] == '11/5'
    assert result['cuts_sha256'] == check.sha(cuts)
    cuts.write_text(payload + '\n')
    with pytest.raises(check.VerificationError, match='cuts hash'):
        check.verify_search_cuts(root, path)
    evidence['cuts_sha256'] = check.sha(cuts)
    dump(path, evidence)
    with pytest.raises(check.VerificationError, match='exact reconstruction'):
        check.verify_search_cuts(root, path)
    cuts.write_text(payload)
    evidence['cuts_sha256'] = check.sha(cuts)
    evidence['witness']['x'] = ['0']*9
    dump(path, evidence)
    with pytest.raises(check.VerificationError, match='infeasible dose'):
        check.verify_search_cuts(root, path)
    evidence['witness']['x'] = ['1']+['0']*8
    evidence['cuts'][0]['lambda'] = ['-1']
    dump(path, evidence)
    with pytest.raises(check.VerificationError, match='dimensions/sign'):
        check.verify_search_cuts(root, path)


def test_zero_weights_removed_before_integer_expansion(monkeypatch):
    from fractions import Fraction
    a = np.array([[.1, np.nextafter(0., 1.), .3], [.5, .7, .9]])
    actual_dyadic = check._dyadic
    shapes = []
    def record_shape(values):
        shapes.append(values.shape)
        return actual_dyadic(values)
    monkeypatch.setattr(check, '_dyadic', record_shape)
    for weights, transpose, expected_shape in [
        ([Fraction(0), Fraction(1, 2**1100), Fraction(3, 7)], False, (2, 2)),
        ([Fraction(0), Fraction(1, 2**1100)], True, (1, 3)),
    ]:
        integers, denominator = check._common(weights)
        result = check._weighted(a, integers, denominator, transpose=transpose)
        matrix = a.T if transpose else a
        expected = [sum((Fraction(float(v))*w for v, w in zip(row, weights)), Fraction(0)) for row in matrix]
        assert result == expected
        assert shapes[-1] == expected_shape
        count = len(shapes)
        zeros = np.zeros(len(weights), dtype=object)
        assert check._weighted(a, zeros, 1, transpose=transpose) == [0]*len(matrix)
        assert len(shapes) == count
