"""Entrena en PC sin utilizar test.csv para elegir ni ajustar parametros."""
import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import warnings

from backend.dataset import FEATURES, FEATURE_VERSION
from backend.ml_runtime import LogisticModel
from backend.storage import utc_now
from .package import DatasetPackage


def classification_metrics(truth, prediction):
    from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
    precision, recall, f1, support = precision_recall_fscore_support(truth, prediction, labels=[0, 1], zero_division=0)
    matrix = confusion_matrix(truth, prediction, labels=[0, 1]).tolist()
    return {'classes': ['normal', 'anomalo'], 'confusionMatrix': matrix,
            'accuracy': float(accuracy_score(truth, prediction)), 'macroF1': float(sum(f1) / 2),
            'falsePositives': matrix[0][1], 'falseNegatives': matrix[1][0],
            'perClass': {name: {'precision': float(precision[i]), 'recall': float(recall[i]),
                               'f1': float(f1[i]), 'support': int(support[i])} for i, name in enumerate(('normal', 'anomalo'))}}


def train(dataset, output, *, allow_simulated=False):
    import numpy as np
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import LeaveOneGroupOut
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    with DatasetPackage(dataset, allow_simulated=allow_simulated) as package:
        rows = package.read('train')
        if not rows:
            raise ValueError('No hay observaciones elegibles de entrenamiento.')
        x = np.asarray([row['features'] for row in rows], dtype=float)
        y = np.asarray([row['y'] for row in rows], dtype=int)
        groups = np.asarray([row['group'] for row in rows])
        if len(set(groups)) < 2 or set(y) != {0, 1}:
            raise ValueError('Se requieren dos sesiones de entrenamiento y ambas clases.')
        if np.isnan(x).all(axis=0).any():
            raise ValueError('Una caracteristica no tiene valores en entrenamiento. Revisa el piloto y los sensores.')

        def pipeline():
            return Pipeline([('imputer', SimpleImputer(strategy='median')), ('scaler', StandardScaler()),
                             ('classifier', LogisticRegression(C=1, solver='lbfgs', class_weight='balanced', max_iter=1000))])

        folds, cross_prediction = [], np.empty(len(rows), dtype=int)
        with warnings.catch_warnings():
            warnings.simplefilter('error', ConvergenceWarning)
            for training, validation in LeaveOneGroupOut().split(x, y, groups):
                if set(y[training]) != {0, 1} or np.isnan(x[training]).all(axis=0).any():
                    raise ValueError('Un pliegue de validacion no tiene ambas clases o valores disponibles. Recolecta mas sesiones.')
                fitted = pipeline().fit(x[training], y[training])
                prediction = fitted.predict(x[validation])
                cross_prediction[validation] = prediction
                folds.append({'heldOutSession': str(groups[validation[0]]), 'trainingRows': len(training),
                              'validationRows': len(validation), 'metrics': classification_metrics(y[validation], prediction)})
            fitted = pipeline().fit(x, y)
        imputer, scaler, classifier = (fitted.named_steps[name] for name in ('imputer', 'scaler', 'classifier'))
        data = {'modelSchema': 1, 'featureVersion': FEATURE_VERSION, 'featureNames': list(FEATURES),
                'classes': ['normal', 'anomalo'], 'imputation': imputer.statistics_.tolist(),
                'mean': scaler.mean_.tolist(), 'scale': scaler.scale_.tolist(),
                'coef': classifier.coef_[0].tolist(), 'intercept': float(classifier.intercept_[0]),
                'provenance': {'source': package.manifest['source'], 'trainingRows': len(rows),
                               'trainingSessions': sorted(set(str(item) for item in groups)),
                               'trainingCsvSha256': package.manifest['sha256']['train.csv'],
                               'datasetManifestSha256': package.manifest_hash},
                'training': {'createdAt': utc_now(), 'algorithm': 'LogisticRegression',
                             'parameters': {'C': 1, 'solver': 'lbfgs', 'class_weight': 'balanced', 'max_iter': 1000},
                             'python': platform.python_version(),
                             'versions': {name: version(name) for name in ('scikit-learn', 'numpy', 'scipy')}}}
        lightweight = LogisticModel(data, allow_simulated=allow_simulated)
        for original, expected_score, expected_class in zip(rows, fitted.predict_proba(x)[:, 1], fitted.predict(x)):
            features = {name: None if np.isnan(value) else float(value) for name, value in zip(FEATURES, original['features'])}
            actual = lightweight.predict(features)
            if abs(actual['score'] - expected_score) > 1e-9 or int(actual['label'] == 'anomalo') != expected_class:
                raise ValueError('El JSON no reproduce el pipeline; no se publica el modelo.')
        report = {'source': data['provenance']['source'], 'rows': len(rows), 'folds': folds,
                  'crossValidation': classification_metrics(y, cross_prediction), 'testUsedForFit': False,
                  'parityTolerance': 1e-9, 'testReserved': True}
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=False)
    model_text = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
    report['modelId'] = hashlib.sha256(model_text.encode('utf-8')).hexdigest()
    report['datasetManifestSha256'] = data['provenance']['datasetManifestSha256']
    (folder / 'model.json').write_bytes(model_text.encode('utf-8'))
    (folder / 'training-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description='Entrena una regresion logistica en PC. No evalua ni ajusta usando prueba.')
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--output', required=True, help='Carpeta nueva para modelo e informe')
    parser.add_argument('--allow-simulated', action='store_true', help='Solo pruebas de software; nunca acredita datos reales')
    args = parser.parse_args()
    try:
        report = train(args.dataset, args.output, allow_simulated=args.allow_simulated)
        print(f"Modelo guardado. Procedencia: {report['source']}. Filas de entrenamiento: {report['rows']}. Prueba reservada.")
    except Exception as error:
        parser.exit(1, f'No se entreno el modelo: {error}\n')


if __name__ == '__main__':
    main()
