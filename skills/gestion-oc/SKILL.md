---
name: gestion-oc
description: Gestiona órdenes de cambio (OC) de servicios de AWS de la empresa: registrar una solicitud de cambio de un valor o de un recurso nuevo, evaluarla (riesgo, impacto, plan y vuelta atrás), consultar su estado y anotar novedades. Úsala cuando el usuario pida cambiar un valor de un servicio, solicitar un recurso, o pregunte por una orden de cambio, su estado o qué falta para aprobarla.
metadata:
  version: "1.0"
---

# Gestión de órdenes de cambio

Una **orden de cambio (OC)** es la petición formal de cambiar algo en AWS. Este sistema **solo hace seguimiento**:
nunca modifica recursos. Alguien ejecuta el cambio fuera de aquí y después se verifica.

## Flujo (siempre el mismo)

`solicitada → evaluada → aprobada → programada → ejecutada → verificada`

Salidas: `rechazada`, `cancelada` (antes de ejecutar) y `revertida` (después de ejecutar).

## Qué haces tú y qué NO

| Tú (herramientas del gateway) | Solo una persona, desde la web |
|-------------------------------|--------------------------------|
| `listar_oc`, `consultar_oc` | Aprobar o rechazar |
| `registrar_oc` | Programar, ejecutar, verificar |
| `evaluar_oc` | Cancelar o revertir |
| `agregar_nota_oc` | |

Si te piden aprobar, programar, ejecutar o cerrar una orden, **no lo intentes**: explica que lo hace una persona desde
la pestaña «Órdenes de cambio» y dile qué le falta a la orden para que pueda hacerlo.

## Pasos

1. **Mira antes de actuar.** Llama a `listar_oc` (o `consultar_oc` con el id) y trabaja solo con ids que devuelvan
   las herramientas. Nunca inventes ni acortes un id.
2. **Registrar una solicitud** con `registrar_oc`:
   - Cambiar un valor → `tipo: modificar_valor`, y rellena `servicio`, `recurso`, `parametro`, `valor_actual` (si lo
     sabes) y `valor_propuesto`.
   - Pedir algo nuevo → `tipo: nuevo_recurso`, con `servicio` y una `justificacion`.
   - Deduce `titulo` y `justificacion` de lo que dijo el usuario. Pregunta **una sola cosa** y solo si falta el
     servicio o, en un cambio de valor, el parámetro o el valor nuevo. No pidas más datos.
3. **Evaluar** con `evaluar_oc` (solo órdenes `solicitada`). Exige los cuatro campos:
   - `riesgo`: `baja`, `media` o `alta`.
   - `impacto`: qué se afecta y cuánto dura (una frase).
   - `plan`: cómo se haría el cambio, en pasos cortos.
   - `rollback`: cómo se vuelve atrás si sale mal.
   Criterio de riesgo: **alta** si afecta producción con corte, datos o seguridad; **media** si es producción sin
   corte previsto; **baja** si es un entorno de pruebas o un valor sin efecto en usuarios. En la duda, sube un nivel.
4. **Anotar** con `agregar_nota_oc` lo que sea relevante (una decisión, un dato que falta, una duda para el
   aprobador).
5. **Responder** en español, breve, diciendo en qué estado quedó la orden y cuál es el siguiente paso humano.

## Errores

Si una herramienta devuelve `error`, léelo: dice qué falta o qué está mal. Corrígelo y reintenta **una vez**; si
sigue fallando, cuéntaselo al usuario con claridad.

Más detalle y ejemplos: [references/campos-y-ejemplos.md](references/campos-y-ejemplos.md).
