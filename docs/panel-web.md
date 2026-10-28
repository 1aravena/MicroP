# Panel web · Grupo C

El panel controla Uno y Nano conectados por USB al equipo que ejecuta el backend. La Raspberry recibe y guarda; el navegador del PC muestra y controla. La aplicación sirve página, recursos y API desde un único proceso, sin dependencias nuevas de ejecución ni conexión a internet.

## Abrir el panel

Ejecutar desde la raíz del repositorio con el entorno virtual del backend.

Para comprobarlo en el PC:

```powershell
.\.venv\Scripts\python.exe -m backend
```

Abrir `http://127.0.0.1:8001/`. Puede abrirse sin Arduino: mostrará el servicio y el almacenamiento, con las placas desconectadas.

En Raspberry, después de la preparación indicada en [la guía del backend](raspberry-backend.md):

```sh
.venv/bin/python -m backend --host 0.0.0.0
```

Desde el PC de la misma red, abrir `http://IP_DE_LA_RASPBERRY:8001/`, reemplazando el marcador por la IP real. No se necesita iniciar un servidor estático separado para este panel. Se conserva el arranque manual con una sola instancia.

El servicio utiliza la red local de confianza y no incluye login ni roles de usuarios. No publicarlo en internet. La autorización del acceso físico y el ML pertenecen a etapas posteriores.

## Acceso desde GitHub Pages

La portada de Pages abre `index.html`, el diagnóstico USB. Su tarjeta **Panel web · Ensayos y dataset** enlaza a `panel.html#ensayos`. El panel también se publica directamente en `https://1aravena.github.io/MicroP/panel.html#ensayos`.

Pages sirve archivos estáticos y no ejecuta el backend Python ni SQLite. En ese alojamiento se muestra un aviso y se desactivan los controles y las consultas periódicas; los contadores indican **Sin consultar**. El acceso **Abrir panel conectado en este PC** abre `http://127.0.0.1:8001/#ensayos` si Python está funcionando allí. Para usar Raspberry, abrir su IP con el puerto 8001 en la misma red. La página del backend consulta su propia API; no se envían peticiones desde Pages a una API externa ni se cambia CORS.

Para otros alojamientos estáticos puede identificarse el documento con `<html lang="es" data-hosting="static">`. Este indicador solo desactiva la conexión; no genera datos de demostración.

## Conectar y capturar

1. Conectar los Arduino con los firmwares de protocolo 2 al equipo que ejecuta el backend y cerrar otros programas que ocupen sus puertos.
2. Pulsar **Actualizar puertos** y seleccionar el puerto de cada placa. Son puertos de la Raspberry, no del navegador. No se asignan roles por el nombre o fabricante USB.
3. Pulsar **Conectar UNO** o **Conectar NANO**. El backend verifica identidad y confirma STOP; una placa equivocada se rechaza.
4. Revisar pines y sensores conforme al cableado real. Los predeterminados son sugerencias. Pulsar **Aplicar configuración**.
5. Pulsar **Iniciar captura** de cada placa que se utilizará. Puede funcionar una sola placa.
6. Observar lecturas, gráficos, contador y recepción. **Detener** afecta únicamente esa placa. Cambiar pines requiere detener; los interruptores permiten habilitar sensores durante la captura con confirmación del backend.

Los cambios de configuración detenida son borradores locales: no modifican la Raspberry hasta aplicarlos y bloquean el inicio mientras estén pendientes. Si otra pestaña cambia la configuración o inicia la captura, se recupera el estado confirmado y se descartan borradores incompatibles con un aviso.

**Cerrar, recargar o dejar de mirar la página no detiene la adquisición.** Al volver se consulta la captura existente; el navegador no crea otro UUID ni envía START automáticamente. Las distintas pestañas controlan las mismas placas y comparten el estado del backend.

## Lecturas, gráficos y archivos

- Uno muestra distancia en cm, luz en lux y sonido como DO bruto 0/1; Nano muestra PIR y radar digitales. Sonido no representa dB ni una polaridad de detección confirmada.
- Las lecturas distinguen sensor desactivado, valor no disponible, espera de muestra, ausencia de datos recientes, placa desconectada y pérdida de comunicación con Raspberry.
- Cada gráfica conserva como máximo 300 filas de la captura mostrada para su placa. Al reabrir se recuperan las más recientes desde SQLite. Mínimos, máximos y transiciones corresponden a esa ventana, no al historial completo.
- El eje usa fecha/hora de recepción de la Raspberry, mostrada en la zona horaria del navegador. El reloj original del Arduino se conserva en los datos. No se mezclan valores de placas distintas ni se crean filas para cubrir huecos.
- Con la captura detenida o el enlace perdido, la gráfica queda identificada como **Historial reciente**; las cifras antiguas no se presentan como lectura actual. Se puede consultar una muestra con el puntero o las flechas/Home/End del teclado.
- **Capturas guardadas** muestra las más recientes, veinte por página. Permite filtrar por origen, navegar a las más antiguas y descargar un CSV por captura. Los estados son capturando, detenida o interrumpida.
- Los CSV se descargan directamente del backend y contienen el corte completo de registros guardados al solicitar la descarga, aunque la gráfica solo muestre 300. No se reconstruyen desde el buffer de la página.
- **Actividad e incidencias** muestra los últimos quince eventos persistidos. Su CSV incluye todo el registro, no solo esos quince.
- Los contadores son lecturas recibidas, no ventanas etiquetadas ni observaciones válidas de prueba ML.

## Errores y recuperación

Una pérdida del enlace HTTP muestra **Sin comunicación**, bloquea controles y conserva los gráficos como historial. Las consultas se reanudan automáticamente cuando vuelve el servicio; los comandos no se repiten automáticamente.

Después de un control sin confirmar se bloquea esa placa hasta obtener un estado actualizado. Si hubo un reinicio del Arduino o una captura interrumpida, aplicar la configuración y comenzar otra captura según el estado que informe el backend.

Desconectar Nano no detiene Uno. Un almacenamiento no disponible se muestra por separado de la comunicación con el servicio; no se presenta una captura como guardada por el hecho de que el navegador esté abierto. Un error puede verse tanto en la placa como en los registros persistidos.

El panel utiliza consultas de hasta cinco segundos y controles de hasta treinta segundos, adecuados a los tiempos predeterminados del backend. Si se modifica sustancialmente `command_timeout` del servidor, revisar también el tiempo del cliente; un timeout del navegador no cancela un comando ya recibido por el servidor.

## Diagnóstico USB separado

`index.html` conserva el diagnóstico USB directo, servido como antes por localhost del PC o por una publicación HTTPS. En el PC puede abrirse con:

```powershell
python -m http.server 8000 --bind 127.0.0.1
```

Abrir `http://127.0.0.1:8000/` en Chrome de escritorio. Esta página usa los USB del PC y mantiene sus registros en memoria hasta descargarlos. Su aviso de descarga antes de cerrar sigue vigente.

El panel Raspberry usa la API y funciona por HTTP local. El diagnóstico USB usa Web Serial y requiere un contexto seguro; no se ofrece el HTTP de la IP de Raspberry como entrada USB del navegador. Un mismo puerto no puede estar simultáneamente abierto por ambos programas.

## Arquitectura e interfaces

- `sensor-ui.js` comparte construcción de tarjetas y preferencia de tema, sin compartir el control de las capturas.
- `api-client.js` encapsula HTTP, errores y URLs de descarga; no contiene datos simulados.
- `remote-panel.js` mantiene snapshots del backend, borradores, consultas, cursores y buffers acotados. Descarta respuestas anteriores a operaciones o cambios de filtro.
- `panel.js` representa el estado y enlaza las acciones. El controlador USB, transporte serial y protocolo existentes conservan su responsabilidad.
- `charts.js` permite un eje de recepción con fechas para Raspberry; su comportamiento predeterminado sigue siendo el tiempo relativo del diagnóstico USB.
- El servidor publica `/` y los recursos de `/css` y `/js`. No monta el directorio completo del repositorio. API y página comparten origen; no se agrega CORS abierto.

El estado de las placas se consulta aproximadamente cada segundo, sin ciclos solapados. Salud, primera página de capturas e incidencias se actualizan cada cinco segundos y después de controles. Las páginas históricas conservan su posición durante el polling. Los puertos se enumeran al cargar, recuperar el enlace o solicitarlo manualmente.

### Orden y paginación

`GET /api/v1/captures`, `/samples` e `/incidents` admiten `order=asc|desc`; el valor predeterminado sigue siendo `asc`. Se mantienen `{items, nextCursor}`, filtros y límites de 1 a 500.

- `asc`: devuelve IDs mayores que `after_id`, en orden creciente.
- `desc`, `after_id=0`: comienza con los más recientes.
- `desc`, cursor no cero: devuelve IDs menores que ese cursor, en orden decreciente.
- `nextCursor` es el último ID numérico de esa página; una página vacía conserva el cursor de entrada.
- En capturas el cursor es el ordinal numérico, distinto del UUID usado para identificarlas y exportarlas.
- Para recibir muestras nuevas después de una consulta descendente se usa el **mayor ID recibido** como cursor ascendente, no el último cursor descendente.

Ejemplo de recuperación reciente:

```text
/api/v1/samples?capture_id=UUID_CAPTURA&order=desc&limit=300
```

La etapa original del panel no requirió migración. La gestión de [ensayos y dataset](ensayos-dataset.md) utiliza ahora esquema 2, con respaldo previo; conserva las cabeceras CSV originales y el protocolo serial.

## Validación de software

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
node --test
```

Las pruebas incluyen orden y filtros, cursores, exportación completa con más de 300 registros, exclusión de archivos privados, recuperación de capturas, buffers, borradores, respuestas tardías, exclusión por placa, almacenamiento, timeout y errores HTTP. Las comprobaciones de firmware siguen utilizando dobles nativos, sin acreditar compilación para los cores reales.

Verificación local del 27 de octubre de 2026: **73 pruebas Python y 84 JavaScript aprobadas**. En navegador se comprobó conexión/configuración/inicio de ambas placas simuladas, recuperación del mismo UUID al recargar, activación de sensores, desconexión aislada de Nano, datos antiguos, reconexión, control compartido entre pestañas y consulta de gráficos por teclado. Una descarga real desde el botón del panel conservó 584 filas simuladas consecutivas. También se revisaron escritorio, pantalla móvil sin desbordamiento horizontal, ambos temas y la carga independiente del diagnóstico USB. No se usó hardware real.

La comprobación en navegador utiliza exclusivamente un servidor de QA independiente:

```powershell
.\.venv\Scripts\python.exe -m backend.tests.panel_browser_fixture --port 8012
```

Ese servidor se identifica como **PERIFÉRICOS SIMULADOS**, utiliza una base temporal y rutas `/test/` exclusivas de la prueba. El arranque normal del backend no importa esa fábrica ni expone esas rutas. Ningún CSV de esta comprobación es un dataset real.

## Estado y validación física pendiente

- [x] Página y recursos servidos junto con la API.
- [x] Cliente HTTP y estados remotos independientes por placa.
- [x] Configuración, controles y conciliación con el backend.
- [x] Recuperación de datos recientes, gráficos y memoria acotada.
- [x] Lista paginada, filtros y descargas persistidas.
- [x] Pruebas de software y comprobación visual con periféricos simulados.
- [ ] Instalar y ejecutar en la Zero 2 W real.
- [ ] Confirmar modelos, cableado y firmwares de ambas placas.
- [ ] Capturar 15 minutos, registrar memoria y comprobar descarga mientras se adquiere.
- [ ] Cerrar y reabrir el panel durante una captura sin generar otra.
- [ ] Comprobar desconexión aislada y recuperación con los equipos reales.
- [ ] Reiniciar el backend, verificar el historial y comenzar una captura nueva.
- [ ] Adjuntar CSV reales y resultados a la [pauta física](validacion-hardware.md).

El panel incluye ahora navegación entre Sensores y Ensayos y dataset, con detención global del ensayo activo y controles individuales bloqueados durante su reserva. Ver la [guía de sesiones, revisión y exportación](ensayos-dataset.md). La validación física permanece pendiente, junto con autorización, actuadores y ML.
