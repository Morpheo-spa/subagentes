# Página: Entrar (override de MASTER)

Objetivo: entrar en menos de diez segundos desde un puesto compartido de planta u oficina.

## Layout
- Sin app shell. Una `Card` de 448px centrada en `min-h-dvh`; debajo, solo el selector de idioma.
- Dentro: `h1` "Entrar en Estampa" (es el único encabezado de la página: no hay topbar que lo lleve),
  una línea de contexto, correo, contraseña, un botón primario.

## Reglas
- Label visible siempre; `autoComplete` (`username`, `current-password`) para gestores de contraseñas
  y lectores de pantalla. `noValidate`: los errores los da el servidor y se muestran junto a la
  contraseña, con `role="alert"`, sin caja (aviso en línea = icono + texto).
- Un solo error genérico ("correo o contraseña incorrectos"): nunca se dice cuál de los dos falla.
- Mientras se rehidrata la sesión desde la cookie no se enseña el formulario: `Skeleton` del
  tamaño de la tarjeta, `aria-busy`. Un formulario que parpadea y desaparece es peor que un hueco.
- Botón: `SignIn` 20px + "Entrar"; en curso, "Entrando…" y `disabled`. Sin spinner.
- Sin "recordarme", sin registro, sin enlaces sociales: las cuentas las crea la empresa.
- 375: la tarjeta ocupa el ancho con gutter 16; el teclado no tapa el botón (`gap-4`, sin footer fijo).
