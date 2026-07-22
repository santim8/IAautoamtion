# Estructura del archivo A02

El A02 es un archivo de **texto plano posicional (ancho fijo)**: cada campo ocupa N caracteres en
una posición exacta, sin separadores. El servicio `/activation-file` lo genera a partir del JSON.

## Layout (parcial — confirmado por el Excel de negocio)

| Campo | Long | Pos inicial |
|---|---|---|
| Tipo de Novedad | 2 | 1 |
| Numero producto referencia cruzada | 14 | 3 |
| Numero de tarjeta asignado | 19 | 17 |
| Tipo de persona | 1 | 36 |
| Tipo de identificación | 1 | 37 |
| Numero de identificación | 15 | 38 |
| Primer apellido | 15 | 53 |
| Segundo apellido | 15 | 68 |
| Primer nombre | 15 | 83 |
| Segundo nombre | 15 | 98 |
| Nombre corto | 20 | 113 |
| Nombre de realce | 26 | 133 |
| Fecha de nacimiento | 8 | 159 |
| Sexo | 1 | 167 |
| Estado civil | 1 | 168 |
| Dirección residencial Línea 1 | 40 | 169 |
| Dirección residencial Línea 2 | 40 | 209 |

> Layout completo PENDIENTE — Juan Carlos debe entregar el Excel completo + ejemplos TXT.

## Reglas de formato

- Rellenar con **espacios** o **ceros** según el tipo de campo, para mantener anchos exactos.
- Fechas internas del archivo en formato **YYMMDD** (ojo: el request HTTP usa `YYYYMMDD`).
- **Aumentos** usan estructura simplificada: **sin nombres ni apellidos**. El validador/generador
  debe ramificar por tipo de novedad.
- Validar nomenclatura del nombre del archivo, BIN de la tarjeta, código de unidad de negocio y consecutivos.

## Activación vs Aumento

| | Activación | Aumento |
|---|---|---|
| Estructura | Completa (incluye nombres, apellidos, dirección) | Simplificada (sin nombres/apellidos) |
| tipoNovedad | (a confirmar: 1) | 2 |

## Validación con el Programa Desatendido (Python)

El programa abre el `.txt` y verifica posiciones/longitudes. Ejemplo conceptual:

```python
linea = open("A0288000128040154321.txt").read()

tipo_novedad = linea[0:2]      # pos 1-2
num_tarjeta  = linea[16:35]    # pos 17-35
num_id       = linea[37:52]    # pos 38-52
# ... comparar contra el request y validar longitudes/relleno
```

No intercepta el SFTP: opera sobre el **contenido del archivo** (generado local, bajado de S3 o del SFTP).
