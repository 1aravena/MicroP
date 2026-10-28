"""Inferencia de regresion logistica; solo biblioteca estandar en Raspberry."""
import hashlib
import json
import math
from pathlib import Path

from .dataset import FEATURES, FEATURE_VERSION, finite


class LogisticModel:
    def __init__(self, data, *, allow_simulated=False, model_id=None):
        if not isinstance(data, dict) or data.get('modelSchema') != 1 or data.get('featureVersion') != FEATURE_VERSION:
            raise ValueError('Version de modelo incompatible.')
        if data.get('featureNames') != list(FEATURES) or data.get('classes') != ['normal', 'anomalo']:
            raise ValueError('Variables o clases incompatibles.')
        provenance = data.get('provenance', {})
        if not isinstance(provenance, dict) or provenance.get('source') not in ('real', 'simulated') or (provenance['source'] != 'real' and not allow_simulated):
            raise ValueError('Se requiere un modelo entrenado con datos reales.')
        for name in ('imputation', 'mean', 'scale', 'coef'):
            vector = data.get(name)
            if not isinstance(vector, list) or len(vector) != len(FEATURES) or not all(finite(value) for value in vector):
                raise ValueError('Parametros de modelo invalidos.')
        if not all(value > 0 for value in data['scale']) or not finite(data.get('intercept')):
            raise ValueError('Escalado o intercepto invalido.')
        self.data = data
        self.id = model_id or hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()

    @classmethod
    def load(cls, path, *, allow_simulated=False):
        file = Path(path)
        if file.stat().st_size > 1048576:
            raise ValueError('El modelo supera el limite de un MiB.')
        raw = file.read_bytes()
        return cls(json.loads(raw), allow_simulated=allow_simulated, model_id=hashlib.sha256(raw).hexdigest())

    def predict(self, features):
        if not isinstance(features, dict) or set(features) != set(FEATURES):
            raise ValueError('Vector de caracteristicas incompatible.')
        transformed = []
        for index, name in enumerate(FEATURES):
            value = features[name]
            if value is None:
                value = self.data['imputation'][index]
            if not finite(value):
                raise ValueError('Caracteristica no finita.')
            transformed.append((value - self.data['mean'][index]) / self.data['scale'][index] * self.data['coef'][index])
        z = self.data['intercept'] + math.fsum(transformed)
        if not math.isfinite(z):
            raise ValueError('Resultado de modelo no finito.')
        score = 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))
        return {'label': 'anomalo' if z > 0 else 'normal', 'score': score, 'modelId': self.id}


class ModelRuntime:
    def __init__(self, path, *, allow_simulated=False):
        self.model = None
        self.state = 'no_model'
        self.error = 'Sin modelo. Entrena en el PC y configura el JSON antes de reiniciar el backend.'
        try:
            self.model = LogisticModel.load(path, allow_simulated=allow_simulated)
            self.state, self.error = 'ready', ''
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            self.state, self.error = 'error', 'Modelo invalido o incompatible; revisa su version, procedencia y parametros.'

    def status(self):
        return {'state': self.state, 'error': self.error, 'modelId': self.model.id if self.model else None,
                'featureVersion': FEATURE_VERSION, 'featureNames': list(FEATURES),
                'source': self.model.data['provenance']['source'] if self.model else None}
