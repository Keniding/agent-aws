# Campos y ejemplos de órdenes de cambio

## Campos de una orden

| Campo | Obligatorio | Notas |
|-------|-------------|-------|
| `titulo` | Sí | Corto y concreto: «Subir memoria de la Lambda de pagos» |
| `tipo` | Sí | `modificar_valor` o `nuevo_recurso` |
| `servicio` | Sí | Nombre del servicio de AWS: Lambda, DynamoDB, S3, Cognito… |
| `recurso` | No | Nombre o ARN del recurso afectado |
| `parametro` | Solo en `modificar_valor` | Qué se cambia: `MemorySize`, `Timeout`, retención de logs… |
| `valor_actual` | No | Si se conoce |
| `valor_propuesto` | Solo en `modificar_valor` | El valor nuevo |
| `justificacion` | Recomendado | Por qué hace falta |

## Ejemplo 1 · cambiar un valor

Usuario: «Necesitamos subir la memoria de la Lambda de pagos de 256 a 512 MB porque hay timeouts en los picos.»

Tú: `registrar_oc` con `tipo: modificar_valor`, `servicio: Lambda`, `recurso: pagos`, `parametro: MemorySize`,
`valor_actual: 256`, `valor_propuesto: 512`, `justificacion: Timeouts en picos`.
Después, si te piden evaluarla: `evaluar_oc` con `riesgo: media`, `impacto: Despliegue de configuración sin corte
previsto`, `plan: Actualizar MemorySize a 512 en la plantilla y desplegar`, `rollback: Volver a 256 y desplegar`.

## Ejemplo 2 · recurso nuevo

Usuario: «Pide una cola SQS para los avisos de facturación.»

Tú: `registrar_oc` con `tipo: nuevo_recurso`, `servicio: SQS`, `titulo: Cola SQS para avisos de facturación`.
No creas la cola: solo queda registrada la solicitud para que una persona la evalúe y la apruebe.

## Ejemplo 3 · te piden aprobar

Usuario: «Aprueba la orden de la Lambda.»

Tú: no puedes. Responde: «Aprobar lo hace una persona desde la pestaña Órdenes de cambio. Está evaluada con riesgo
medio, así que ya puede aprobarse.» (usa `consultar_oc` para saber su estado real antes de contestar).
