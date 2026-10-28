# Protocolo serial 2

El montaje final usa [pasarela maestro/esclavo version 1](integracion-final.md#contrato-de-pasarela-1): UART Raspberry-Uno a 115200 y Uno-Nano a 9600. La envoltura agrega rol e ID sin cambiar mensajes de ocho columnas ni CSV. El contrato directo que sigue se conserva para diagnostico USB. Nano 33 BLE utiliza Serial1 en sus pines y Serial en USB; D2/D3 del Uno se reservan en modo maestro.

La extension opcional de senalizacion del Nano incorpora `SIGNAL_CAPS` y `SIGNAL,<uuid>,ALLOW|DENY|FAULT|OFF`, con ACK correlacionado, patrones no bloqueantes y apagado autonomo. Ver el [contrato de acceso](acceso-y-fallas.md#led-y-protocolo). INFO, adquisicion, mascaras y las ocho columnas de sensores conservan su formato. El backend comprueba esta capacidad solo al activar acceso; el firmware anterior sigue siendo util para adquisicion.

Contrato comun de los firmwares Uno/Nano, la pagina de diagnostico y el backend Python. Transporte: USB/serial, 115200 baudios, 8N1, una linea por mensaje terminada en LF. Se acepta CRLF. Los comandos distinguen mayusculas y no admiten espacios ni campos vacios. No hay checksum adicional en esta version: se valida estructura, origen, tipos, rangos y secuencia; no se afirma detectar toda corrupcion posible.

## Identidad y ciclo de vida

Al arrancar, la placa emite `@READY,2,UNO` o `@READY,2,NANO`. Esta identidad indica el **rol del firmware cargado**, no detecta el modelo electronico ni certifica que el cableado sea correcto.

1. El navegador abre un puerto y espera el posible reinicio USB.
2. Envia `INFO`; espera `@OK,INFO,2,UNO` o `@OK,INFO,2,NANO`.
3. Comprueba version y rol contra el boton utilizado. Rechaza un firmware anterior o una placa equivocada y libera ese puerto.
4. Envia `STOP` y requiere configuracion explicita del usuario antes de iniciar.
5. Antes de CONFIG vuelve a verificar INFO y STOP. El usuario solo configura sensores con la captura detenida.

Cada instancia mantiene su propio comando pendiente y timeout de 4 segundos. Un error de lectura `@ERR,READ,...` no cancela un comando pendiente. `@READY` durante una conexion identificada invalida la configuracion y termina la captura local; exige configurar nuevamente.

## Comandos y respuestas

| Comando | Respuesta correcta |
| --- | --- |
| `INFO` | `@OK,INFO,2,UNO` o `@OK,INFO,2,NANO` |
| `CONFIG,trigger,echo,pir,radar,sonido,hc_on,pir_on,radar_on,lux_on,sonido_on` | `@OK,CONFIG` |
| `START` | `@OK,START` |
| `STOP` | `@OK,STOP` |
| `ENABLE,HC,0` (tambien PIR, RADAR, LUX, SOUND; 0/1) | `@OK,ENABLE,HC,0` |

CONFIG mantiene cinco posiciones de pin y cinco banderas para ambos roles. Todos los campos de pin son enteros 0..255; solo se usan y validan como D2..D12 aquellos asociados a sensores activos. Las banderas son 0/1. Uno solo permite HC, LUX y SOUND; Nano solo PIR y RADAR. No puede haber pines repetidos entre funciones activas de una misma placa. El mismo numero en otra placa es independiente. D0/D1 quedan reservados para serial y D13 queda fuera de este contrato.

Los pines I2C no son campos configurables. Wire utiliza el bus predeterminado de la placa seleccionada al compilar; se debe verificar el pinout fisico.

Ejemplos de configuracion (pines **sugeridos**, pendientes de comprobar):

```text
CONFIG,4,5,6,7,8,1,0,0,1,1
CONFIG,4,5,6,7,8,0,1,1,0,0
```

La configuracion se confirma despues de validar formato, rol, pines y presencia del BH1750 si esta activo. Si falla, no se reemplaza la configuracion confirmada anterior. El navegador invalida su permiso local de inicio y solicita volver a aplicar, porque un timeout puede dejar incierto el resultado de un comando.

START requiere CONFIG confirmado, rechaza una captura ya activa y reinicia `secuencia` a 0 y el reloj relativo. La primera muestra tiene secuencia 1 y se envia aproximadamente un segundo despues. STOP es idempotente. ENABLE permite modificar sensores sin cambiar pines; se aplica la nueva mascara al recibir su ACK exacto. Los mensajes anteriores al ACK corresponden a la mascara anterior.

## Mediciones

Ocho campos, sin cabecera enviada por la placa:

```text
origen,secuencia,tiempo_ms,distancia_cm,pir_estado,radar_estado,lux,sonido_estado
```

Ejemplos **ilustrativos para probar el protocolo, no capturas fisicas**:

```text
UNO,1,1000,84.30,NA,NA,182.50,0
NANO,1,1000,NA,1,0,NA,NA
UNO,2,2000,NA,NA,NA,180.00,1
```

- Origen: UNO o NANO, debe coincidir con el puerto identificado.
- Secuencia: entero positivo uint32, creciente dentro de una captura. Duplicados y mensajes fuera de orden se descartan; saltos se registran.
- Tiempo: milisegundos uint32 desde START. Cada placa tiene un reloj independiente; no se presentan como sincronizados.
- Distancia: 2..400 cm. Sin eco o fuera de rango se envia NA y una incidencia de lectura.
- PIR y radar: estado digital instantaneo 0/1, con la retencion propia de cada modulo.
- Luz: lectura finita no negativa en lux. Un fallo se envia como NA y no elimina las otras mediciones de esa fila.
- Sonido: nivel electrico instantaneo DO 0/1. No representa dB, volumen, cantidad de sonidos ni una polaridad de deteccion confirmada.
- Sensores ajenos al rol o desactivados: obligatoriamente NA.
- Sensor activo invalido: NA. El navegador distingue esta condicion de la desactivacion mediante la mascara confirmada y registra MISSING aun si no recibio la linea de error de la placa.

La adquisicion instantanea a 1 Hz puede perder pulsos breves. La cantidad de transiciones observadas no es la cantidad total de eventos fisicos. No hay calibracion certificada. Los sensores digitales tampoco permiten detectar automaticamente un cable desconectado.

## Errores y recuperacion

Errores de control: `@ERR,COMMAND,UNKNOWN`, `@ERR,COMMAND,FORMAT`, `@ERR,COMMAND,TOO_LONG`, `@ERR,CONFIG,FORMAT`, `@ERR,CONFIG,PINS_OR_ROLE`, `@ERR,CONFIG,BH1750_NOT_FOUND`, `@ERR,STATE,NOT_CONFIGURED`, `@ERR,STATE,CAPTURE_ACTIVE`, `@ERR,ENABLE,FORMAT` y `@ERR,ENABLE,SENSOR`.

Errores de lectura: `@ERR,READ,HC_SR04_NO_VALID_ECHO` y `@ERR,READ,BH1750`. En el siguiente mensaje de datos se mantienen las mediciones validas.

Firmware: buffer de comando de 96 bytes (95 de contenido). Una linea desbordada se descarta completa hasta LF; despues se aceptan nuevos comandos. Navegador: limite de 512 caracteres por linea, con la misma recuperacion. Un error de una placa no detiene la otra. Ante timeout de START/STOP/ENABLE no se afirma conocer el estado fisico: se cierra la captura local y se exige STOP y nueva configuracion. Una desconexion conserva el historial descargable.

## Exportacion

CSV de mediciones:

```text
fecha_hora_recepcion,captura_id,origen,secuencia,tiempo_ms,distancia_cm,pir_estado,radar_estado,lux,sonido_estado
```

La fecha/hora es UTC del **equipo receptor**: el PC en diagnostico USB o la Raspberry cuando ejecuta el backend. No procede del reloj Arduino. `captura_id` es un UUID nuevo por cada START confirmado. Los campos posteriores a esos dos metadatos reproducen el mensaje recibido y validado. No se fusionan ni completan filas con valores de otra placa. En la pagina USB, los graficos utilizan un eje monotono comun de recepcion del PC y separan las series por origen y por captura actual.

CSV de incidencias: `fecha_hora,origen,tipo,descripcion`. Incluye conexiones, CONFIG confirmado, START/STOP, ENABLE, reinicios, errores, lecturas faltantes y saltos de secuencia. El texto se escapa para CSV y se neutralizan prefijos de formula en los campos de texto recibidos.

En la pagina USB, los historiales viven en la memoria de la pestaña y la descarga crea un archivo persistente. El backend Python guarda automaticamente en SQLite y exporta el mismo formato desde disco; ver la [guia del backend](raspberry-backend.md). La pantalla USB grafica la captura actual de cada placa. Ninguno de estos registros constituye por si solo ventanas de ML, conjuntos etiquetados ni validacion del requisito de observaciones de la Solemne.
