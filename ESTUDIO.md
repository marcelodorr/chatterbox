# Estúdio de Voz

Interface web estilo estúdio de voz (texto para fala + clonagem de voz) sobre os modelos open-source
**Chatterbox** (Resemble AI, licença MIT), com **servidor MCP + OAuth 2.1** para usar direto do
**Claude** e do **ChatGPT**.

```
┌─────────── VPS (Dokploy) ───────────────────────────────┐
│                                                         │
│  api  (FastAPI, porta 8000, domínio público HTTPS)      │
│   ├─ /             interface React                      │
│   ├─ /api/*        API da interface (sessão por cookie) │
│   ├─ /oauth/*      servidor OAuth 2.1 (PKCE, DCR)       │
│   ├─ /mcp          servidor MCP (Bearer token)          │
│   ├─ fila de geração + SQLite + arquivos em /data       │
│   │                                                     │
│   └──HTTP interno──► inference (porta 8001, privada)    │
│                      Chatterbox em CPU ou GPU           │
└─────────────────────────────────────────────────────────┘
```

O serviço `inference` é separado de propósito: hoje roda em CPU no mesmo VPS; quando quiser GPU,
sobe o mesmo container numa máquina com GPU e troca só a variável `INFERENCE_URL` da API.

## Funcionalidades

- **Texto para fala** com voz, modelo, idioma, expressividade, ritmo e variação; textos longos são
  divididos em trechos automaticamente (até 5.000 caracteres por padrão).
- **Biblioteca de vozes**: voz padrão do modelo, vozes clonadas por você e vozes compartilhadas pelo admin.
- **Clonagem de voz** por upload (WAV/MP3/M4A/OGG/WEBM) ou gravação no navegador, com termo de consentimento obrigatório.
- **Histórico** de gerações, com player e download em WAV.
- **Usuários**: o admin cria contas; o cadastro público é opcional.
- **MCP para Claude e ChatGPT** com OAuth: cada pessoa autoriza com a própria conta e pode revogar em “Claude e ChatGPT”.

### Modelos disponíveis

| id       | Modelo                         | Idiomas          | Observação                                  |
|----------|--------------------------------|------------------|---------------------------------------------|
| `mtl-v3` | Chatterbox Multilingual V3     | 23 (inclui `pt`) | Padrão. 500M parâmetros                     |
| `pt-br`  | Finetune português do Brasil   | `pt`             | Melhor sotaque BR. 500M                     |
| `turbo`  | Chatterbox Turbo               | `en`             | Tags `[laugh]`, `[cough]`… 350M             |
| `nano`   | Chatterbox Nano                | `en`             | Mais leve, bom em CPU. 110M                 |

Os pesos são baixados do Hugging Face no primeiro uso e ficam no volume `models`.

## Deploy no Dokploy

1. Use este repositório (branch `estudio-de-voz`) como fonte no Dokploy.
2. No Dokploy, crie um projeto → **Create Service → Compose**, aponte para o repositório e use o
   arquivo `docker-compose.yml`.
3. Em **Environment**, cole o conteúdo de `.env.example` e preencha:
   - `PUBLIC_URL` – a URL HTTPS final, ex.: `https://voz.seudominio.com`
   - `SECRET_KEY` – `openssl rand -base64 48`
   - `INFERENCE_TOKEN` – `openssl rand -hex 32`
   - `ADMIN_EMAIL` / `ADMIN_PASSWORD` – o primeiro administrador
4. Em **Domains**, adicione o domínio ao serviço **`api`**, porta **8000**, com HTTPS (Let's Encrypt).
   Não exponha o serviço `inference`.
5. **Deploy.** O primeiro build demora (PyTorch) e a primeira geração também (download de ~3 GB do modelo).
   Acompanhe nos logs do `inference` até aparecer `modelo mtl-v3 carregado`.
6. Acesse `https://voz.seudominio.com`, entre com o admin e teste uma geração.

### Requisitos do VPS (sem GPU)

- **RAM:** 8 GB no mínimo (um modelo de 500M em CPU usa ~4 GB). Mantenha `MAX_LOADED_MODELS=1`.
- **Disco:** ~10 GB livres (imagens + pesos dos modelos).
- **CPU:** quanto mais núcleos, melhor. Em CPU a geração do `mtl-v3` é **mais lenta que o tempo real**:
  conte com dezenas de segundos para um parágrafo. A fila processa um pedido por vez.
  Para testes rápidos em inglês, use o modelo `nano`.

### Migrando para GPU (pago por uso)

1. Em uma máquina com GPU NVIDIA, suba só o serviço de inferência com
   `TORCH_INDEX=https://download.pytorch.org/whl/cu124` e o bloco `deploy.resources` (comentado no compose) ativado.
2. Exponha-o com HTTPS e o mesmo `INFERENCE_TOKEN`.
3. Na API, defina `INFERENCE_URL=https://seu-worker-gpu` e remova o serviço `inference` local.

## Conectando ao Claude e ao ChatGPT

A URL do conector é **`{PUBLIC_URL}/mcp`** (também aparece na tela “Claude e ChatGPT”).

**Claude** (claude.ai / Desktop): Configurações → Conectores → *Adicionar conector personalizado* →
cole a URL → Conectar → faça login no estúdio → **Permitir**. Deixe Client ID/Secret em branco: o
Claude se registra sozinho (Dynamic Client Registration).

**ChatGPT**: Configurações → Apps e conectores → Configurações avançadas → ative o *Modo desenvolvedor* →
*Criar* → cole a URL, autenticação **OAuth** → login → **Permitir**.

Ferramentas expostas: `list_voices`, `list_models`, `generate_speech`, `get_generation`,
`list_generations` e `clone_voice`. Como Claude e ChatGPT não tocam áudio inline, o resultado traz um
**link assinado de download** (válido por 7 dias). Se a geração passar de ~45 s, a ferramenta devolve o
id e o assistente consulta com `get_generation`.

### Detalhes do OAuth

- Metadata: `/.well-known/oauth-authorization-server` (RFC 8414) e `/.well-known/oauth-protected-resource` (RFC 9728)
- Registro dinâmico de clientes (RFC 7591) e Client ID Metadata Documents (client_id em URL https)
- Authorization Code + PKCE S256 obrigatório; token vinculado ao recurso `/mcp` (RFC 8707)
- Access token de 1 h; refresh token de 60 dias com rotação e detecção de reuso; revogação (RFC 7009)
- Tela de consentimento com proteção CSRF e anti-clickjacking
- Em produção, recomendo `OAUTH_ALLOWED_REDIRECT_HOSTS=claude.ai,claude.com,chatgpt.com,localhost,127.0.0.1`

## Desenvolvimento local

O PyTorch 2.6 exigido pelo Chatterbox **não tem build para Mac Intel**, então o motor de voz roda em Docker:

```bash
cp .env.example .env    # preencha; para local use PUBLIC_URL=http://localhost:8000
docker compose up --build
# acrescente "ports: ['8000:8000']" ao serviço api para acessar http://localhost:8000
```

Para mexer só na interface/API sem o motor de voz:

```bash
# API
cd server && uv venv --python 3.11 .venv && uv pip install -r requirements.txt
DATA_DIR=./data PUBLIC_URL=http://localhost:8000 INFERENCE_URL=http://localhost:8001 \
  .venv/bin/uvicorn app.main:app --reload --port 8000

# Interface (proxy para a API em :8000)
cd web && npm install && npm run dev   # http://localhost:5173
```

Para testar o MCP localmente com o Claude/ChatGPT, exponha a porta 8000 com um túnel HTTPS
(ex.: `cloudflared tunnel --url http://localhost:8000`) e use a URL do túnel em `PUBLIC_URL`.

## Estrutura

```
src/chatterbox/  código original dos modelos (não modificado)
inference/       serviço HTTP de inferência (engine.py: carga de modelos, cache de vozes, divisão de texto)
server/app/      API: auth.py, api.py, oauth.py, mcp.py, jobs.py (fila), services.py, db.py (SQLite)
web/             interface React + Vite + Tailwind
```

## Uso responsável

- A clonagem exige que a pessoa confirme ser dona da voz ou ter autorização; a data do consentimento fica registrada.
- Todo áudio gerado pelo Chatterbox leva a marca d'água inaudível **PerTh** da Resemble AI.
- O projeto Chatterbox foi **descontinuado em agosto de 2026** (arquivado, sem atualizações). Ele continua
  funcionando, mas não haverá correções.
