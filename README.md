# Deteccion y seguridad de acceso — Grupo 2

Proyecto experimental de la Solemne 1. Un Arduino Uno adquiere cinco sensores y envia una muestra conjunta por segundo a una pagina web estatica mediante USB y Web Serial. La pagina permite configurar pines, activar sensores, ver lecturas reales y descargar la sesion como CSV sin backend ni almacenamiento remoto.

## Sensores

| Sensor | Variable | Conexion de datos |
| --- | --- | --- |
| HC-SR04 | Distancia en cm | Trigger y Echo configurables |
| HC-SR501 | Movimiento 0/1 | Pin digital configurable |
| RCWL-0516 | Movimiento 0/1 | Pin digital configurable |
| BH1750 / GY-30 | Iluminancia en lux | SDA=A4 y SCL=A5, fijos por I2C |
| LM393 sonido | Evento acustico 0/1 | Pin digital configurable |

Los pines configurables pueden ser D2 a D12. D0 y D1 quedan reservados para Serial y D13 no se utiliza. La interfaz impide que dos funciones **activas** compartan un pin.

## Dependencias Arduino

En Arduino IDE, abre **Herramientas > Administrar bibliotecas** e instala:

- `BH1750` de Christopher Laws (claws).
- `NewPing` de Tim Eckel.

`BH1750` se utiliza en el programa integrado y en su prueba individual. `NewPing` se utiliza en `arduino/individuales/hc_sr04.ino`. El firmware integrado lee el HC-SR04 directamente con `pulseIn()` y un tiempo maximo: NewPing fija Trigger/Echo al construir el objeto y no ofrece setters para cambiarlos durante la ejecucion. Evitar reconstrucciones dinamicas mantiene el codigo y la memoria del Uno simples y predecibles.

## Conexion sugerida

Todos los modulos y el Arduino deben compartir GND.

| Modulo | Alimentacion | Señal predeterminada |
| --- | --- | --- |
| HC-SR04 | VCC a 5V, GND a GND | Trigger D4, Echo D5 |
| HC-SR501 | VCC a 5V, GND a GND | OUT D6 |
| RCWL-0516 | VIN a 5V, GND a GND | OUT D7 |
| BH1750 / GY-30 | VCC y GND segun el modulo | SDA A4, SCL A5 |
| LM393 sonido | VCC a 5V, GND a GND | DO D8 |

Si cambias un pin en la pagina, mueve tambien el cable correspondiente. Los potenciometros o ajustes fisicos de PIR y LM393 no se controlan por software.

## Cargar el firmware integrado

1. Abre `arduino/integrado/integrado.ino` en Arduino IDE.
2. Selecciona **Arduino Uno** y el puerto correcto.
3. Instala la biblioteca BH1750 si falta.
4. Compila y carga el sketch.
5. Cierra el Monitor Serial antes de conectar desde la pagina; un puerto no puede ser usado por ambas aplicaciones al mismo tiempo.

El firmware usa 115200 baudios. Al iniciar una captura espera 1000 ms antes de la primera fila y luego programa las lecturas con `millis()`. No se detiene automaticamente al alcanzar 300 registros.

## Abrir la pagina localmente

Web Serial requiere un contexto seguro. Usa Chrome de escritorio y sirve esta carpeta desde `localhost`, por ejemplo:

```bash
python3 -m http.server 8000
```

Abre `http://localhost:8000`. No abras `index.html` directamente porque los modulos JavaScript pueden ser bloqueados por el navegador.

## Uso durante la demostracion

1. Pulsa **Conectar Arduino** y elige el puerto USB de la placa.
2. Activa solamente los sensores que quieras probar.
3. Selecciona los pines que coincidan con el cableado. A4/A5 del BH1750 no cambian.
4. Pulsa **Aplicar configuracion**. Arduino vuelve a validar rango, duplicados y presencia del BH1750 cuando esta activo.
5. Pulsa **Iniciar captura**. Los selectores de pines quedan bloqueados.
6. Observa las lecturas. Los interruptores siguen disponibles; un cambio valido se envia con `ENABLE`.
7. Para cambiar pines, pulsa **Detener captura**, modifica, aplica y vuelve a iniciar.
8. Mantiene la sesion oficial aproximadamente cinco minutos hasta ver `✓ Minimo de 300 registros alcanzado`.
9. Deten la captura y pulsa **Descargar CSV**.

Cada nueva captura limpia las filas de la captura anterior. Antes de iniciar una nueva, descarga cualquier sesion que necesites conservar. Una desconexion fisica detiene el estado de captura, pero las filas ya recibidas siguen disponibles para descarga mientras no se recargue la pagina.

## Archivo CSV

La cabecera es siempre:

```text
tiempo_ms,distancia_cm,pir_estado,radar_estado,lux,sonido_estado
```

| Columna | Significado |
| --- | --- |
| `tiempo_ms` | Milisegundos desde que Arduino inicio la captura |
| `distancia_cm` | Distancia HC-SR04 en centimetros; 0.00 indica que no hubo eco dentro del limite |
| `pir_estado` | HC-SR501: 0 sin movimiento, 1 con movimiento |
| `radar_estado` | RCWL-0516: 0 sin movimiento, 1 con movimiento |
| `lux` | Iluminancia BH1750 en lux |
| `sonido_estado` | LM393: 0 sin evento, 1 evento detectado |

Un sensor desactivado ocupa `NA`; el orden y la cantidad de columnas nunca cambian. La pagina solo guarda filas validas recibidas realmente desde Arduino y descarta una linea malformada sin detener la sesion.

## Protocolo Serial

La pagina envia una instruccion por linea:

```text
CONFIG,trigger,echo,pir,radar,sonido,hc_on,pir_on,radar_on,lux_on,sonido_on
START
STOP
ENABLE,PIR,1
```

Las respuestas de control comienzan con `@OK` o `@ERR`. Las muestras no llevan prefijo y siempre contienen las seis columnas del CSV, por ejemplo:

```text
1000,84.30,0,0,182.50,0
2000,NA,1,NA,NA,0
```

## Pruebas individuales

Los cinco programas requeridos estan en subcarpetas de `arduino/individuales/`. Arduino exige que el archivo principal tenga el mismo nombre que su carpeta y compila juntos todos los `.ino` ubicados en un mismo directorio; por eso cada prueba tiene su propia carpeta:

- `hc_sr04/hc_sr04.ino`
- `hc_sr501/hc_sr501.ino`
- `rcwl0516/rcwl0516.ino`
- `bh1750/bh1750.ino`
- `lm393_sonido/lm393_sonido.ino`

Cada programa lee solamente su sensor y muestra un resultado comprensible en el Monitor Serial a 115200 baudios. Carga un sketch a la vez y conecta el modulo al pin indicado en sus comentarios.

## Publicar en GitHub Pages

1. Sube esta carpeta a un repositorio de GitHub.
2. En el repositorio abre **Settings > Pages**.
3. En **Build and deployment**, selecciona **Deploy from a branch**.
4. Elige la rama principal y la carpeta `/ (root)`.
5. Abre la URL HTTPS publicada con Chrome de escritorio.

GitHub Pages solo sirve los archivos estaticos; los datos viajan entre el navegador y el Arduino local y no se suben a GitHub.

## Secuencia recomendada de evaluacion

- Prueba HC-SR04 con al menos dos distancias.
- Prueba presencia y ausencia con HC-SR501.
- Prueba RCWL-0516 y compara su respuesta con el PIR.
- Prueba al menos dos niveles de iluminacion con BH1750.
- Ajusta fisicamente el LM393 y genera un cambio controlado 0/1.
- Activa los cinco sensores y registra 300 o mas filas durante la adquisicion integrada.
