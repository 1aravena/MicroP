import json
import math

import pytest

from backend.dataset import FEATURES
from backend.ml_runtime import LogisticModel, ModelRuntime


def model_data(source='simulated'):
    return {'modelSchema': 1, 'featureVersion': 1, 'featureNames': list(FEATURES), 'classes': ['normal', 'anomalo'],
            'imputation': [1.] * 10, 'mean': [0.] * 10, 'scale': [1.] * 10, 'coef': [0.5] * 10,
            'intercept': -1., 'provenance': {'source': source, 'trainingRows': 20, 'trainingSessions': ['a', 'b'],
                                          'trainingCsvSha256': '0' * 64}}


def test_runtime_requires_real_model_except_explicit_test_transport(tmp_path):
    path = tmp_path / 'model.json'
    assert ModelRuntime(path).state == 'no_model'
    path.write_text(json.dumps(model_data()))
    assert ModelRuntime(path).state == 'error'
    runtime = ModelRuntime(path, allow_simulated=True)
    assert runtime.state == 'ready'
    result = runtime.model.predict(dict.fromkeys(FEATURES, None))
    assert result['label'] == 'anomalo' and result['score'] == pytest.approx(1 / (1 + math.exp(-4)))


@pytest.mark.parametrize('field,value', [('featureVersion', 999), ('coef', [0]), ('scale', [0]*10),
                                      ('intercept', float('nan')), ('classes', ['anomalo', 'normal'])])
def test_runtime_rejects_invalid_parameters(field, value):
    data = model_data(); data[field] = value
    with pytest.raises(ValueError):
        LogisticModel(data, allow_simulated=True)


def test_runtime_stable_extreme_scores_and_missing_feature_validation():
    data = model_data()
    data['intercept'] = 10000
    model = LogisticModel(data, allow_simulated=True)
    assert model.predict(dict.fromkeys(FEATURES, 1))['score'] == 1
    data['intercept'] = -10000
    assert model.predict(dict.fromkeys(FEATURES, 1))['score'] == 0
    with pytest.raises(ValueError):
        model.predict({'label': 'normal'})
    with pytest.raises(ValueError):
        model.predict(dict.fromkeys(FEATURES, float('inf')))
