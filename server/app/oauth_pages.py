from __future__ import annotations

from html import escape

from .config import settings

_STYLE = """
:root{--bg:#f6f6f5;--card:#fff;--fg:#111;--muted:#6b6b6b;--line:#e7e7e4;--accent:#111;--accent-fg:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#0d0d0d;--card:#171717;--fg:#f2f2f2;--muted:#9a9a9a;--line:#2a2a2a;--accent:#f2f2f2;--accent-fg:#111}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:var(--bg);color:var(--fg);font:15px/1.5 Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;max-width:440px;width:100%;padding:28px}
.brand{display:flex;align-items:center;gap:10px;font-weight:600;margin-bottom:22px}
.dot{width:26px;height:26px;border-radius:8px;background:var(--accent)}
h1{font-size:20px;margin:0 0 6px}p{margin:0 0 14px;color:var(--muted)}
.client{display:flex;gap:12px;align-items:center;padding:14px;border:1px solid var(--line);border-radius:12px;margin:18px 0}
.client img{width:36px;height:36px;border-radius:8px;object-fit:cover}
.client b{display:block;color:var(--fg)}.client span{color:var(--muted);font-size:13px;word-break:break-all}
ul{padding-left:18px;margin:0 0 18px;color:var(--fg)}li{margin:4px 0}
.row{display:flex;gap:10px;margin-top:8px}
button{flex:1;border:1px solid var(--line);border-radius:999px;padding:11px 16px;font:inherit;font-weight:600;cursor:pointer;background:transparent;color:var(--fg)}
button.primary{background:var(--accent);color:var(--accent-fg);border-color:var(--accent)}
.foot{font-size:12.5px;color:var(--muted);margin-top:16px}
"""


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
<style>{_STYLE}</style></head><body><div class="card">
<div class="brand"><div class="dot"></div>{escape(settings.app_name)}</div>{body}</div></body></html>"""


def error_page(message: str) -> str:
    return _page("Erro de autorização", f"<h1>Não foi possível autorizar</h1><p>{escape(message)}</p>")


def consent_page(client: dict, user: dict, params: dict, csrf: str, redirect_host: str) -> str:
    name = client.get("client_name") or "Aplicativo sem nome"
    logo = client.get("logo_uri") or ""
    logo_html = f'<img src="{escape(logo)}" alt="" referrerpolicy="no-referrer">' if logo.startswith("https://") else ""
    hidden = "".join(
        f'<input type="hidden" name="{escape(k)}" value="{escape(v)}">' for k, v in params.items() if v is not None
    )
    return _page(
        "Autorizar acesso",
        f"""
<h1>Autorizar acesso</h1>
<p>Conectado como <b>{escape(user['email'])}</b></p>
<div class="client">{logo_html}<div><b>{escape(name)}</b><span>Retorno para {escape(redirect_host)}</span></div></div>
<p>Este aplicativo poderá, em seu nome:</p>
<ul>
<li>Ver suas vozes e as vozes compartilhadas</li>
<li>Gerar áudios de fala (usa a fila de geração)</li>
<li>Clonar novas vozes a partir de um áudio que você autorizar</li>
</ul>
<form method="post" action="/oauth/authorize">
{hidden}<input type="hidden" name="csrf" value="{escape(csrf)}">
<div class="row">
<button type="submit" name="action" value="deny">Cancelar</button>
<button type="submit" name="action" value="allow" class="primary">Permitir</button>
</div></form>
<div class="foot">Você pode revogar este acesso a qualquer momento em Integrações.</div>
""",
    )
