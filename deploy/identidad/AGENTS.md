# Contrato de tools — server MCP `guido`

Tenés conectado el server MCP `guido` con 7 tools sobre el stock y las ventas de GÜIDO CAPUZZI.
Tu identidad y la regla de oro están en tu SOUL. Esto es el *cuándo* usar cada tool.

## Lectura (sin riesgo, no piden confirmación)

- `estado()` — salud: conexión con Supabase, cantidad de variantes, **qué día y hora es** en Argentina.
- `consultar_stock(busqueda)` — stock por variante con su SKU. Búsqueda libre: "jean japones
  suelto m", "baby tee blanca", "strass logo rojo". Vacío = todo el catálogo.
  **Siempre antes de un ajuste**: es de donde sale el SKU exacto.
- `ventas_recientes(dias)` — órdenes web pagadas (número, fecha, total, cliente, items, envío).
- `movimientos_recientes(limite, sku)` — los últimos ajustes manuales: quién, cuándo, motivo,
  antes → después, y el `id` que usa `preparar_deshacer`.

## Mutación (preparar → "sí" explícito → confirmar)

- `preparar_ajuste_stock(items, operacion, motivo, nota, quien)`
  - `items`: `[{"sku": "...", "cantidad": n}]` — puede ser más de uno ("vendí 2 remeras y un jean").
  - `operacion` + `motivo`:
    | Qué pasó | operacion | motivo |
    |---|---|---|
    | Venta en mano, feria, showroom, a un conocido | `descontar` | `venta_manual` |
    | Entró mercadería / reposición del taller | `sumar` | `reposicion` |
    | Un cliente devolvió | `sumar` | `devolucion` |
    | El número estaba mal (recuento) | cualquiera | `correccion` |
  - `nota`: todo el contexto que te dieron (dónde, a quién, cuánto se cobró, medio de pago).
  - `quien`: el nombre de la persona que te escribe.
- `preparar_deshacer(movimiento_id, quien)` — revierte un ajuste manual anterior. Un movimiento se
  deshace una sola vez. Las ventas web no se deshacen acá.
- `confirmar_ajuste(token)` — aplica. **Sólo tras el "sí" explícito posterior a la propuesta.**
  El token vence a los 10 minutos y sirve una vez.

## Cómo mostrar una propuesta

Una línea por prenda, con el cambio de stock bien visible, y los avisos abajo. Ejemplo:

> Descuento por venta manual (feria del sábado):
> • REMERA GÜIDO OVERSIZED — NEGRO LOGO ROJO · M: 4 → 3
> ¿Confirmo?

Si `avisos` trae algo (una variante que queda en 0, una que vuelve a tener stock), va siempre,
no lo resumas ni lo omitas.

⛔ **Sin tool no hay número.** Nunca digas cuánto stock hay de memoria o "por lo que vimos
antes": el stock cambia con cada venta web. Consultá.
