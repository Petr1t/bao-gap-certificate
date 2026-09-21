#!/usr/bin/env python3
"""Build a synthetic, patient-data-free example the verifier accepts end to end.

The geometry is deliberately trivial (two voxels, 72 beams with one beamlet
each, every influence coefficient equal to one), so the whole example is a few
megabytes and carries no clinical information. It exercises the same code path
as a real cohort packet: offline model verification, rederivation from the
"original" source files, and the exact rational certificate.

The costs follow the model of the study: c_j = sum_S theta_S * mean_{v in S} A_vj
with theta = 1 (RECTUM), 3/5 (BLADDER), 3/5 (BODY). Here every mean is 1, so
c_j = 11/5 for every beamlet.

Certificate values, all exact rationals:
  lower  lambda = 11/5 on the single PTV row. A^T lambda - c = 0, so no beamlet
         penalty is subtracted and L = 11/5, which is the true LP optimum.
  planner x = 1 on the first supported beamlet: dose 1 >= 1, U = 11/5, gap 0 %.
  raster  x = 3/2 on the first supported beamlet: dose 3/2 >= 1, U = 33/10,
          gap 100*(33/10 / (11/5) - 1) = 50 %.
"""
import argparse
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np

PATIENT = 'Prostate_Patient_1'
REVISION = 'a' * 40
BEAMS = 72
RASTER = list(range(0, 65, 8))
PLANNER = list(range(9))


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(4 << 20), b''):
            h.update(block)
    return h.hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def build_source(source):
    (source / 'Beams').mkdir(parents=True)
    dump(source / 'CT_MetaData.json', {'resolution_xyz_mm': [1, 1, 1]})
    with h5py.File(source / 'OptimizationVoxels_Data.h5', 'w') as f:
        f['ct_to_dose_voxel_map'] = np.array([[[-1, 0, 1]]], dtype=np.int64)
    with h5py.File(source / 'StructureSet_Data.h5', 'w') as f:
        f['PTV'] = np.array([[[0, 1, 0]]], dtype=np.uint8)
        for name in ('RECTUM', 'BLADDER', 'BODY'):
            f[name] = np.array([[[0, 0, 1]]], dtype=np.uint8)
    dump(source / 'OptimizationVoxels_MetaData.json',
         {'ct_to_dose_voxel_map_File': 'OptimizationVoxels_Data.h5/ct_to_dose_voxel_map'})
    dump(source / 'StructureSet_MetaData.json',
         [{'name': n, 'structure_mask_3d_File': f'StructureSet_Data.h5/{n}'}
          for n in ('PTV', 'RECTUM', 'BLADDER', 'BODY')])
    dump(source / 'PlannerBeams.json', {'IDs': PLANNER})
    for i in range(BEAMS):
        with h5py.File(source / f'Beams/Beam_{i}_Data.h5', 'w') as f:
            f['inf_matrix_full'] = np.ones((2, 1), dtype=np.float32)
        dump(source / f'Beams/Beam_{i}_MetaData.json',
             {'ID': i, 'gantry_angle': 5 * i, 'couch_angle': 0, 'collimator_angle': 0,
              'influenceMatrixFull_File': f'Beam_{i}_Data.h5/inf_matrix_full'})


def build_model(model, source):
    beams = []
    for i in range(BEAMS):
        filename = f'beam-{i:03}.h5'
        with h5py.File(model / filename, 'w') as f:
            f['A'] = np.ones((1, 1), dtype=np.float32)
            f.create_dataset('c_num', data=['11'], dtype=h5py.string_dtype('utf-8'))
            f.create_dataset('c_den', data=['5'], dtype=h5py.string_dtype('utf-8'))
        beams.append({'id': i, 'gantry': 5 * i, 'couch': 0, 'collimator': 0,
                      'columns': 1, 'file': filename, 'sha256': sha(model / filename)})
    manifest = {
        'schema': 1, 'patient': PATIENT, 'revision': REVISION,
        'model': {'xmax': 1000, 'target': 'PTV',
                  'weights': {'RECTUM': '1', 'BLADDER': '3/5', 'BODY': '3/5'},
                  'normalization': 'Ax>=1', 'mean': 'flat-dose-voxel'},
        'n_voxels': 2, 'ptv_indices': [0],
        'structures': {'PTV': [0], 'RECTUM': [1], 'BLADDER': [1], 'BODY': [1]},
        'planner_ids': PLANNER, 'beams': beams,
        'source_files': {str(p.relative_to(source)): sha(p)
                         for p in sorted(source.rglob('*')) if p.is_file()},
    }
    dump(model / 'model.json', manifest)


def build_certificate(model):
    certificate = {
        'schema': 1,
        'model_sha256': sha(model / 'model.json'),
        'lower': {'lambda': ['11/5'], 'value': '11/5'},
        'upper': {
            'planner': {'beam_ids': PLANNER, 'x': ['1'] + ['0'] * 8, 'value': '11/5'},
            'raster': {'beam_ids': RASTER, 'x': ['3/2'] + ['0'] * 8, 'value': '33/10'},
        },
    }
    dump(model / 'certificate.json', certificate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='example', help='output directory (created)')
    args = parser.parse_args()
    out = Path(args.out)
    model, source = out / 'model', out / 'source'
    model.mkdir(parents=True)
    build_source(source)
    build_model(model, source)
    build_certificate(model)
    print(f'model:       {model}')
    print(f'source:      {source}')
    print(f'certificate: {model / "certificate.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
