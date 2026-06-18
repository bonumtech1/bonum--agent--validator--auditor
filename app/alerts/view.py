"""Página HTML mínima para ver las alertas en el navegador.

No es el dashboard final (eso lo hará React consumiendo /alerts). Es una vista
simple y sin dependencias para revisar las alertas mientras tanto.
"""

import html

_SEVERITY_DOT = {"high": "🔴", "medium": "🟡", "info": "🟢"}
_STATUS_LABEL = {
    "nueva": "Nueva",
    "revisada": "Revisada",
    "ignorada": "Ignorada",
    "escalada": "Escalada",
}


def render_alerts_page(alerts: list[dict]) -> str:
    if alerts:
        rows = "\n".join(_render_row(a) for a in alerts)
    else:
        rows = '<tr><td colspan="6" class="empty">No hay alertas 🎉</td></tr>'

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Centro de Alertas — Auditoría</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f7f7f8; color: #1a1a1a; }}
  h1 {{ font-size: 1.4rem; }}
  .sub {{ color: #666; margin-bottom: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff;
           border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  th, td {{ padding: .75rem 1rem; text-align: left; border-bottom: 1px solid #eee; font-size: .9rem; }}
  th {{ background: #fafafa; font-weight: 600; }}
  .empty {{ text-align: center; color: #888; padding: 2rem; }}
  .badge {{ padding: .15rem .5rem; border-radius: 999px; font-size: .75rem; background: #eee; }}
  .nueva {{ background: #ffe9e0; color: #b1400a; }}
  .revisada {{ background: #e3f0ff; color: #1357a6; }}
  .ignorada {{ background: #eee; color: #777; }}
  .escalada {{ background: #ffe0e6; color: #b00538; }}
</style>
</head>
<body>
  <h1>🔔 Centro de Alertas</h1>
  <p class="sub">{len(alerts)} alerta(s). Esta es una vista provisional; el dashboard final irá en React.</p>
  <table>
    <thead>
      <tr><th></th><th>Tipo</th><th>Título</th><th>Descripción</th><th>Coach</th><th>Estado</th></tr>
    </thead>
    <tbody>
{rows}
    </tbody>
  </table>
</body>
</html>"""


def _render_row(a: dict) -> str:
    sev = _SEVERITY_DOT.get(a.get("severity", ""), "")
    status = a.get("status", "nueva")
    status_label = _STATUS_LABEL.get(status, status)
    return (
        "<tr>"
        f"<td>{sev}</td>"
        f"<td>{html.escape(str(a.get('type', '')))}</td>"
        f"<td>{html.escape(str(a.get('title', '')))}</td>"
        f"<td>{html.escape(str(a.get('description', '')))}</td>"
        f"<td>{html.escape(str(a.get('coach_id') or '—'))}</td>"
        f'<td><span class="badge {status}">{html.escape(status_label)}</span></td>'
        "</tr>"
    )
