# Entrenamiento en PC e inferencia en Raspberry

Estado: herramientas y pruebas de software implementadas. **No se ha entrenado un modelo real ni obtenido métricas del montaje**, porque todavía no hay un dataset real. Las métricas de fixtures son exclusivamente pruebas del código.

## Preparar el entorno del PC

Se probó el entrenamiento en Windows con Python 3.13. Las dependencias están fijadas en `requirements-ml.txt`; este entorno es independiente del servidor. No instalar scikit-learn en Raspberry para ejecutar el JSON.

Desde MicroP:

```powershell
python -m venv .venv-ml
.\.venv-ml\Scripts\python.exe -m pip install -r requirements-ml.txt
```

Para ejecutar todas las pruebas en ese entorno:

```powershell
.\.venv-ml\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv-ml\Scripts\python.exe -m pytest backend/tests -q
node --test
```

El entorno base conserva sus dependencias actuales. Si se ejecutan las pruebas allí, el archivo de pruebas de entrenamiento indica explícitamente que necesita el entorno ML; esa omisión no acredita que el entrenamiento haya sido probado.

La verificacion de esta etapa ejecuto la suite completa en `.venv-ml`: 120 pruebas Python aprobadas. Incluye exportacion, evaluacion sin refit, hashes, ausencia de uso de test para ajuste y un JSON entrenado con fixtures que se ejecuta en el monitor de ventanas. Todas esas mediciones son de pruebas sinteticas, no del prototipo real.

## Datos necesarios

Seguir [ensayos y dataset](ensayos-dataset.md): dos sesiones de entrenamiento y una posterior independiente de prueba, con cuatro escenarios, confirmación humana, ventanas no superpuestas de diez segundos y política de calidad versión 1.

Meta: 200 ventanas de entrenamiento y 100 de prueba, revisadas por escenario. El mínimo docente de 100 se refiere a datos reales de prueba/validación adicionales al entrenamiento. Un paquete parcial puede servir para explorar, pero no completa ese requisito.

Descargar el ZIP de las sesiones cerradas seleccionadas. El lector valida versiones de esquema 2/3 y características 1, hashes y tamaños disponibles, sesiones cerradas de una sola procedencia, fuentes sin compartir entre ensayos, etiquetas coherentes, UUID de capturas y ventanas identificables de diez segundos. No extrae archivos del ZIP a rutas arbitrarias.

Solo se usan estas entradas, en este orden:

```text
distance_mean_cm,distance_min_cm,distance_std_cm,distance_valid_fraction,
pir_high_fraction,pir_rising_edges,radar_high_fraction,radar_rising_edges,
lux_mean,sound_high_fraction
```

Identificadores, escenario, fechas, responsable, partición y etiqueta son metadatos, nunca entradas. Las estadísticas ausentes de distancia siguen como NA en las fuentes. La imputación pertenece al modelo y se registra en su JSON; no cambia capturas ni dataset.

## Entrenar y congelar

Usar una carpeta de salida nueva para conservar los resultados anteriores:

```powershell
.\.venv-ml\Scripts\python.exe -m ml.train --dataset "data/dataset-real.zip" --output "data/modelo-real-01"
```

El programa lee las observaciones de entrenamiento y verifica integridad del paquete. **No interpreta test.csv ni usa sus etiquetas o características para ajustar o seleccionar parámetros.** Exige ambas clases y al menos dos sesiones útiles. Cada pliegue de entrenamiento también debe contener ambas clases y valores disponibles de todas las características.

Pipeline fijo:

1. `SimpleImputer(strategy="median")`, aprendido del entrenamiento de cada pliegue.
2. `StandardScaler`, aprendido de ese mismo entrenamiento.
3. `LogisticRegression(C=1, solver="lbfgs", class_weight="balanced", max_iter=1000)`.

La validación usa `LeaveOneGroupOut`, agrupando por sesión completa. No divide ventanas relacionadas al azar. Una característica sin ningún valor disponible provoca error accionable; no se inventa un cero para ocultarla. Un problema de convergencia impide publicar el modelo.

Después de validar, se ajusta el pipeline con todas las sesiones de entrenamiento y se guardan:

- `model.json`: imputación, medias, escalas, coeficientes, intercepto, orden de entradas, clases, versiones, procedencia y hashes del entrenamiento.
- `training-report.json`: sesiones dejadas fuera, métricas de validación agrupada y comprobación de equivalencia. Declara que prueba no participó en el ajuste.

Se codifica normal=0 y anómalo=1. El JSON calcula `z = intercepto + suma(coeficiente * (valor_imputado - media) / escala)` y su sigmoide estable. Predice anómalo cuando z>0; en z=0 predice normal, como el pipeline. Antes de escribir los archivos se comparan clases y puntajes contra scikit-learn con tolerancia de 1e-9 sobre entrenamiento.

## Evaluar prueba reservada

```powershell
.\.venv-ml\Scripts\python.exe -m ml.evaluate --dataset "data/dataset-real.zip" --model "data/modelo-real-01/model.json" --output "data/modelo-real-01/evaluacion"
```

Esta operación no ejecuta fit ni cambia el modelo. Verifica correspondencia con el hash de entrenamiento, sesiones disjuntas y, para datos reales, ventanas de prueba posteriores a entrenamiento. Requiere ejemplos de ambas clases.

Archivos:

- `metrics.json`: procedencia, cantidades reales, cumplimiento del mínimo, matriz de confusión, accuracy, F1 macro, precisión/recall/F1 y soporte por clase, falsos positivos y negativos.
- `predictions-test.csv`: etiqueta observada/predicha, puntaje e IDs de observación, sesión, ensayo y modelo.
- `confusion-matrix.csv`: filas observadas y columnas predichas, orden normal/anómalo.

Falso positivo: ventana normal clasificada anómala. Falso negativo: ventana anómala clasificada normal. No se fija una precisión ficticia de aceptación. Documentar resultados, balance, condiciones y limitaciones. Si se modifica el diseño tras observar prueba, reservar una nueva evaluación independiente; no presentar el ajuste repetido como una prueba intacta.

`--allow-simulated` existe únicamente para verificar las herramientas con fixtures. Sus informes mantienen procedencia simulada, cero observaciones reales y mínimo no cumplido. Nunca usar esos resultados para la entrega real.

## Instalar el modelo real en Raspberry

1. Conservar modelo, informes y ZIP de origen juntos en los entregables privados.
2. Copiar el JSON real a `data/model.json` de la Raspberry, o configurar `model_file` en el archivo local del servidor.
3. Reiniciar el backend y volver a conectar, configurar e iniciar ambas capturas.
4. Activar **Acceso y ML** y esperar una ventana completa, más la muestra siguiente que confirma el borde temporal.

No existe carga de modelos por una API pública. El proceso lee un archivo local de hasta un MiB y valida versiones, orden de las diez entradas, clases, parámetros finitos y escalas positivas. No deserializa pickle/joblib ni ejecuta contenido del JSON. El SHA-256 identifica los bytes del modelo; no constituye una firma de procedencia.

El servidor normal rechaza modelos marcados como simulados. Solo la fábrica explícita de pruebas permite usarlos. Modelo ausente/inválido se informa en ML sin impedir la regla independiente del PIN cuando el sistema esencial está sano.

## Inferencia y recuperación

Las ventanas comienzan al activar el modo, usando recepción UTC común de ambas capturas. Son completas, no superpuestas y aplican el extractor/calidad existentes. Se espera una muestra posterior al borde de cada placa para asegurar que las filas anteriores ya estén guardadas.

Los datos se consultan por bloques de hasta 500 filas. Un atraso superior a cinco minutos recupera una ventana reciente y registra `ML_LAG`, conservando las fuentes. Se descartan resultados que lleguen después de desactivar/cambiar el modo. Un reinicio no reanuda el modo automáticamente.

`ml_predictions` conserva modelo, capturas, fechas, características, calidad y motivos de descarte. Una ventana sin modelo o sin calidad no se transforma en una predicción normal. Los resultados de ML no se incorporan a las etiquetas del dataset.

El puntaje anómalo es la salida del clasificador para estas situaciones ensayadas; no es una probabilidad calibrada de intención, delito o riesgo real. Se deben probar en vivo al menos dos patrones y explicar falsos positivos, negativos y limitaciones del muestreo.

## Pendientes reales

- [ ] Piloto y cuatro escenarios observables.
- [ ] Sesiones reales separadas y al menos 100 ventanas de prueba utilizables.
- [ ] Entrenamiento real, evaluación congelada y métricas verificadas.
- [ ] JSON real funcionando en Zero 2 W con medición de memoria/latencia.
- [ ] Demostración normal/anómalo, PIN permitido/rechazado y falla recuperada.
- [ ] Dataset, modelo, informes, video y guía incorporados a la entrega académica.
