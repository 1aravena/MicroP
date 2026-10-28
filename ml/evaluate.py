"""Evalua el JSON congelado; nunca vuelve a entrenar ni elige parametros."""
import argparse
import csv
import json
import math
from pathlib import Path

from backend.dataset import FEATURES
from backend.ml_runtime import LogisticModel
from .package import DatasetPackage
from .train import classification_metrics


def evaluate(dataset, model_path, output, *, allow_simulated=False):
    model = LogisticModel.load(model_path, allow_simulated=allow_simulated)
    with DatasetPackage(dataset, allow_simulated=allow_simulated) as package:
        provenance = model.data['provenance']
        if provenance['source'] != package.manifest['source'] or provenance['trainingCsvSha256'] != package.manifest['sha256']['train.csv']:
            raise ValueError('El modelo no corresponde al entrenamiento de este paquete.')
        rows = package.read('test')
        if not rows or {row['y'] for row in rows} != {0, 1}:
            raise ValueError('Se requieren observaciones de prueba de ambas clases.')
        if set(provenance['trainingSessions']) & {row['group'] for row in rows}:
            raise ValueError('Hay sesiones compartidas entre entrenamiento y prueba.')
        if provenance['source'] == 'real':
            training_rows = package.read('train')
            from backend.dataset import milliseconds
            if max(milliseconds(row['metadata']['window_end']) for row in training_rows) > min(milliseconds(row['metadata']['window_start']) for row in rows):
                raise ValueError('La prueba real debe ser posterior al entrenamiento.')
        predictions = []
        for row in rows:
            features = {name: None if math.isnan(value) else value for name, value in zip(FEATURES, row['features'])}
            predictions.append(model.predict(features))
        metrics = classification_metrics([row['y'] for row in rows], [int(item['label'] == 'anomalo') for item in predictions])
        report = {'modelId': model.id, 'source': provenance['source'], 'testRows': len(rows), 'trainingRows': provenance['trainingRows'],
                  'realTestObservations': len(rows) if provenance['source'] == 'real' else 0,
                  'minimumMet': provenance['source'] == 'real' and len(rows) >= 100,
                  'testSessions': sorted({row['group'] for row in rows}), 'metrics': metrics,
                  'datasetManifestSha256': package.manifest_hash, 'modelRefitted': False}
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'metrics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    with (folder / 'predictions-test.csv').open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['observation_id', 'session_id', 'trial_id', 'observed_label', 'predicted_label', 'anomaly_score', 'model_id'])
        for row, prediction in zip(rows, predictions):
            metadata = row['metadata']
            writer.writerow([metadata['observation_id'], row['group'], metadata['trial_id'], metadata['label'], prediction['label'], prediction['score'], model.id])
    with (folder / 'confusion-matrix.csv').open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['observed/predicted', 'normal', 'anomalo'])
        for name, values in zip(('normal', 'anomalo'), metrics['confusionMatrix']):
            writer.writerow([name, *values])
    return report


def main():
    parser = argparse.ArgumentParser(description='Evalua un modelo congelado sobre prueba independiente.')
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--allow-simulated', action='store_true')
    args = parser.parse_args()
    try:
        result = evaluate(args.dataset, args.model, args.output, allow_simulated=args.allow_simulated)
        print(f"Evaluacion guardada. Procedencia: {result['source']}. Observaciones reales de prueba: {result['realTestObservations']}. Minimo cumplido: {result['minimumMet']}.")
    except Exception as error:
        parser.exit(1, f'No se evaluo el modelo: {error}\n')


if __name__ == '__main__':
    main()
