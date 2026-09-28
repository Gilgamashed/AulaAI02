# Tutorial de Login e Usuários Administradores

Guia operacional do SynapseShop para **autenticar na API** e **gerar/gerenciar
usuários administradores**. Complementa a seção "Autenticação JWT, papéis e
throttling" do [README.md](README.md) com o passo a passo executável e os
procedimentos que o README não detalha (superuser, listagem de usuários, troca
de senha e criação de usuário fora do seed).

> **Escopo:** cobre o serviço `api` (Django REST Framework, porta **8000**).
> O microsserviço `inventory` (FastAPI, porta 8001) **não tem autenticação** —
> nenhuma das rotas abaixo se aplica a ele.

---

## Sumário

1. [Como a autenticação funciona neste projeto](#1-como-a-autenticação-funciona-neste-projeto)
2. [Pré-requisitos](#2-pré-requisitos)
3. [Fazer login na API](#3-fazer-login-na-api)
4. [Usuários que já existem no banco](#4-usuários-que-já-existem-no-banco)
5. [Listar os usuários cadastrados](#5-listar-os-usuários-cadastrados)
6. [Gerar um usuário administrador](#6-gerar-um-usuário-administrador)
7. [Criar um usuário comum do zero](#7-criar-um-usuário-comum-do-zero)
8. [Promover, rebaixar, resetar senha e desativar](#8-promover-rebaixar-resetar-senha-e-desativar)
9. [Django Admin em `/admin/`](#9-django-admin-em-admin)
10. [Troubleshooting](#10-troubleshooting)
11. [Checklist rápido de validação](#11-checklist-rápido-de-validação)

---

## 1. Como a autenticação funciona neste projeto

Três decisões definem o modelo de acesso — e é preciso conhecê-las para não
"corrigir" o sistema errado:

| Decisão | Implementação | Onde está |
| ------- | ------------- | --------- |
| **Não existe modelo `User` próprio** | Usa o `django.contrib.auth.models.User` padrão (tabela `auth_user`). `AUTH_USER_MODEL` **não** é definido em nenhum lugar. | `api/config/settings.py` |
| **Papel (role) = `Group` do Django** | Não há campo `role`/`is_admin`. Os papéis são os grupos `admin` e `user`, na tabela `auth_group`. | `api/core/management/commands/seed_auth.py` |
| **Token JWT** | `djangorestframework-simplejwt`; o login devolve um par `access` + `refresh`. | `api/core/urls.py` |

Consequência prática: **um usuário só vira administrador da API por pertencer
ao grupo `admin` ou por ser superuser.** A permissão `IsAdminRole`
(`api/core/permissions.py:18`) testa exatamente essas duas condições:

```python
if user.is_superuser:
    return True
return user.groups.filter(name="admin").exists()
```

### Rotas de autenticação

| Rota | Método | Descrição | Throttle |
| ---- | ------ | --------- | -------- |
| `/api/v1/auth/token/` | POST | Login → `{access, refresh}` | `login` (5/min) |
| `/api/v1/auth/token/refresh/` | POST | Troca o `refresh` por um novo `access` | `login` (5/min) |
| `/api/v1/auth/token/verify/` | POST | Valida um `access` token | — |

Configuração em `api/config/settings.py:146`:

- `access` expira em **5 minutos**; `refresh` em **1 dia**.
- A assinatura usa `JWT_SIGNING_KEY` do `.env`, com `DJANGO_SECRET_KEY` como
  fallback.

### O que cada papel pode fazer

| Verbo | Anônimo | `demo_user` | `demo_admin` | Superuser |
| ----- | ------- | ----------- | ------------ | --------- |
| `GET /api/v1/categories/`, `/items/` | 200 (público) | 200 | 200 | 200 |
| `POST` (criar) | 401 | 201 | 201 | 201 |
| `PUT` / `PATCH` / `DELETE` | 401 | **403** | 200 / 204 | 200 / 204 |
| Django Admin `/admin/` | 302 → login | sem acesso | **acessa** | **acessa** |

> **Não existe endpoint de cadastro.** Não há `/register/`, `/signup/` nem
> rota de criação de usuário na API. Um usuário só passa a existir por
> `seed_auth`, `createsuperuser`, shell do Django ou Django Admin — veja as
> seções [6](#6-gerar-um-usuário-administrador) e
> [7](#7-criar-um-usuário-comum-do-zero).

---

## 2. Pré-requisitos

Ambiente no ar (o serviço `api` responde `/health` com 200):

```bash
docker compose up -d --build
curl http://localhost:8000/health
# {"status": "ok", "service": "synapseshop-api"}
```

Todos os comandos deste tutorial são executados **da raiz do projeto**.

---

## 3. Fazer login na API

### 3.1 Login (PowerShell)

No PowerShell, monte o corpo com `ConvertTo-Json` para evitar o problema
clássico de aspas do `curl.exe` no Windows:

```powershell
$body = @{ username = 'demo_admin'; password = 'demo-admin@Synapse2026' } | ConvertTo-Json -Compress
$t = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/auth/token/' `
                       -Method Post -ContentType 'application/json' -Body $body
$t.access    # token de curta duração (5 min)
$t.refresh   # token de renovação (1 dia)
```

Resposta (200):

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

> **Enviando texto com acento em qualquer `POST` a partir do PowerShell 5.1:**
> o `-Body` como string vira bytes na codepage ANSI (Windows-1252), não em UTF-8,
> e o Django decodifica o corpo como UTF-8 — o resultado é `EletrÃ´nicos` no
> banco, com **201** de resposta, ou seja, o bug passa despercebido. Converta
> para bytes UTF-8 explicitamente:
> ```powershell
> $json  = @{ name = 'Eletrônicos Futuros' } | ConvertTo-Json -Compress
> $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
> Invoke-RestMethod -Uri $url -Method Post -ContentType 'application/json; charset=utf-8' -Body $bytes
> ```
> Veja também a linha correspondente na seção de
> [Troubleshooting](#10-troubleshooting) — o mesmo cuidado vale para *ler*
> respostas com acento.

### 3.2 Login (bash / Linux / macOS / Git Bash)

```bash
curl -X POST http://localhost:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_admin","password":"demo-admin@Synapse2026"}'
```

Para reaproveitar o token numa chamada seguinte sem copiar e colar:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_admin","password":"demo-admin@Synapse2026"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access'])")
```

### 3.3 Usar o token

O `access` vai no header `Authorization` com o prefixo `Bearer`:

```powershell
Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/categories/' `
  -Headers @{ Authorization = "Bearer $($t.access)" }
```

```bash
curl http://localhost:8000/api/v1/categories/ -H "Authorization: Bearer $TOKEN"
```

### 3.4 Renovar o access token

O access expira em 5 minutos. Em vez de refazer login, troque o `refresh`:

```powershell
$rb = @{ refresh = $t.refresh } | ConvertTo-Json -Compress
$novo = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/auth/token/refresh/' `
                          -Method Post -ContentType 'application/json' -Body $rb
$novo.access
```

```bash
curl -X POST http://localhost:8000/api/v1/auth/token/refresh/ \
  -H "Content-Type: application/json" \
  -d '{"refresh":"<seu refresh>"}'
```

### 3.5 Validar um token

```bash
curl -X POST http://localhost:8000/api/v1/auth/token/verify/ \
  -H "Content-Type: application/json" \
  -d '{"token":"<seu access>"}'
# {} -> 200 (válido)
# {"detail":"O token é inválido","code":"token_not_valid"} -> 401
```

### 3.6 Observações importantes

- **Login é por `username`, nunca por e-mail.** O serializer padrão do SimpleJWT
  não habilitou `authenticate_by_password` por e-mail, então o campo `email`
  é ignorado no login.
- **Limite de 5 tentativas por minuto** (`login` e `refresh` compartilham a
  mesma cota). A 6ª requisição dentro da janela devolve **429**. É
  proposital — proteção contra força bruta. Se bater 429 durante os testes,
  espere ~1 minuto.
- **A collection do Postman já faz isso**: importe
  `collections/synapseshop_aula7.postman_collection.json`, defina `base_url`
  como `http://localhost:8000` e rode primeiro os requests da pasta
  *Autenticação* — eles preenchem `token_admin`, `token_user` e
  `refresh_admin` sozinhos.

---

## 4. Usuários que já existem no banco

Consulta direta na tabela `auth_user` do PostgreSQL (estado verificado em
25/09/2026, com o ambiente do Compose no ar):

| id | username | staff | superuser | ativo | grupo (papel) | e-mail | criado em |
| -- | -------- | ----- | --------- | ----- | ------------- | ------ | --------- |
| 1 | `demo_admin` | **sim** | **não** | sim | `admin` | — | 2026-09-23 22:43:42 UTC |
| 2 | `demo_user` | não | não | sim | `user` | — | 2026-09-23 22:43:42 UTC |

Grupos existentes em `auth_group`:

| id | nome | usuários |
| -- | ---- | -------- |
| 1 | `admin` | 1 |
| 2 | `user` | 1 |

Credenciais de desenvolvimento (criadas pelo `seed_auth`):

| Usuário | Papel | Senha (DEV) | O que consegue fazer |
| ------- | ----- | ----------- | -------------------- |
| `demo_admin` | `admin` | `demo-admin@Synapse2026` | Escrever (`POST`) e administrar (`PUT`/`PATCH`/`DELETE`) o catálogo; **entra no Django Admin** |
| `demo_user` | `user` | `demo-user@Synapse2026` | Apenas criar (`POST`); recebe 403 em rotas administrativas |

> **Atenção — nenhum superuser existe.** `demo_admin` tem `is_staff=True`, o
> que já basta para acessar o Django Admin, mas `is_superuser=False`: ele **não**
> enxerga (nem pode editar) as telas de *Usuários* e *Grupos* do Admin. Se você
> precisa administrar contas de usuário pela interface web, crie um superuser
> real — passo a passo na seção [6.2](#62-opção-b--createsuperuser-interativo).

> **Trocar as senhas demo:** defina `SEED_ADMIN_PASSWORD` e
> `SEED_USER_PASSWORD` no `.env`. Porém o `seed_auth` **só aplica a senha na
> criação** do usuário — em execuções seguintes ele não sobrescreve a senha que
> você trocou manualmente. Para trocar a senha de um usuário já existente, use
> a seção [8.2](#82-resetar-senha).

---

## 5. Listar os usuários cadastrados

### 5.1 Pelo Django, dentro do container (recomendado)

```bash
docker compose exec api python api/manage.py shell -c "from django.contrib.auth import get_user_model as G; from django.contrib.auth.models import Group; [print(u.id, '|', u.username, '| staff:', u.is_staff, '| super:', u.is_superuser, '| ativo:', u.is_active, '| grupos:', list(u.groups.values_list('name', flat=True)), '| ultimo login:', u.last_login) for u in G().objects.all().order_by('id')]; print('GRUPOS:', [g.name for g in Group.objects.all()]); print('SUPERUSERS:', [u.username for u in G().objects.filter(is_superuser=True)] or 'nenhum')"
```

Saída:

```
1 | demo_admin | staff: True | super: False | ativo: True | grupos: ['admin'] | ultimo login: 2026-...
2 | demo_user  | staff: False | super: False | ativo: True | grupos: ['user']  | ultimo login: None
GRUPOS: ['admin', 'user']
SUPERUSERS: nenhum
```

> **`ultimo login` quase sempre vem `None`, e isso é esperado.** Desde a versão
> 5.5, o `djangorestframework-simplejwt` passou a ter `UPDATE_LAST_LOGIN = False`
> como padrão, e o bloco `SIMPLE_JWT` de `api/config/settings.py:146` não
> sobrescreve esse valor. Ou seja: **login pela API não grava `last_login`.**
> Esse campo só é preenchido por login no Django Admin
> (`http://localhost:8000/admin/`), que passa por
> `django.contrib.auth.login`. Se você precisar auditar logins da API, acrescente
> `"UPDATE_LAST_LOGIN": True` ao `SIMPLE_JWT` — com o caveat de que a
> configuração do SimpleJWT só é lida no start do processo, então é preciso
> reiniciar o serviço.

### 5.2 Pelo Django, no `.venv` local

No container a `DATABASE_URL` aponta para o host interno `db`; localmente ela
precisa apontar para `localhost` com as credenciais do seu `.env` (montada a
partir do arquivo, sem digitar a senha no comando):

```powershell
$e = @{}; Get-Content .env | Where-Object { $_ -match '^\w+=' } | ForEach-Object { $k,$v = $_ -split '=',2; $e[$k]=$v }
$env:DATABASE_URL = "postgresql://$($e.POSTGRES_USER):$($e.POSTGRES_PASSWORD)@localhost:5432/$($e.POSTGRES_DB)"
.venv\Scripts\python.exe api\manage.py shell -c "from django.contrib.auth import get_user_model as G; [print(u.id, '|', u.username, '|', u.is_staff, u.is_superuser, list(u.groups.values_list('name', flat=True))) for u in G().objects.all().order_by('id')]"
```

### 5.3 Shell interativo (quiser explorar)

```bash
docker compose exec api python api/manage.py shell
```

```python
from django.contrib.auth import get_user_model
User = get_user_model()
User.objects.count()                                   # total de usuários
User.objects.filter(is_superuser=True)                 # superusers
User.objects.filter(groups__name="admin")              # papel admin
User.objects.filter(is_active=False)                   # contas desativadas
User.objects.get(username="demo_admin").groups.values_list("name", flat=True)
```

### 5.4 SQL direto no PostgreSQL

```powershell
$e = @{}; Get-Content .env | Where-Object { $_ -match '^\w+=' } | ForEach-Object { $k,$v = $_ -split '=',2; $e[$k]=$v }
docker compose exec -e PGPASSWORD=$($e.POSTGRES_PASSWORD) db psql -U $e.POSTGRES_USER -d $e.POSTGRES_DB -P pager=off -c "SELECT u.id, u.username, u.is_staff, u.is_superuser, u.is_active, array_agg(g.name) AS grupos FROM auth_user u LEFT JOIN auth_user_groups ug ON ug.user_id = u.id LEFT JOIN auth_group g ON g.id = ug.group_id GROUP BY u.id ORDER BY u.id;"
```

---

## 6. Gerar um usuário administrador

Quatro caminhos. Escolha conforme o que você precisa.

### 6.1 Opção A — `seed_auth` (papel `admin`, o mais simples)

Cria os dois papéis (`admin` e `user`) e os dois usuários demo. É
**idempotente**: pode rodar N vezes sem duplicar nada.

```bash
docker compose exec api python api/manage.py seed_auth
```

```
Papéis criados: 'admin' e 'user'. Usuários: demo_admin (admin), demo_user (user).
```

O que o `demo_admin` ganha: `is_staff=True` + grupo `admin`.
O que ele **não** ganha: `is_superuser` (veja o alerta da seção 4).

Personalizando os nomes de usuário:

```bash
docker compose exec -e SEED_ADMIN_USERNAME=admin -e SEED_ADMIN_PASSWORD='SenhaForte@2026' `
  -e SEED_USER_USERNAME=cliente -e SEED_USER_PASSWORD='OutraSenha@2026' `
  api python api/manage.py seed_auth
```

> **Armadilha:** as variáveis `SEED_*` **não estão declaradas** no
> `docker-compose.yml`. Escrever `SEED_ADMIN_PASSWORD` no `.env` não basta —
> o Compose não as injeta no serviço `api`. Só funcionam com a flag `-e` acima
> (como no exemplo) ou rodando o comando pelo `.venv` local, onde o `.env` já
> está no ambiente.

### 6.2 Opção B — `createsuperuser` interativo

```bash
docker compose exec api python api/manage.py createsuperuser
```

O prompt pede `Username`, `Email` e `Password` (digite duas vezes). O usuário
nasce com `is_staff=True`, `is_superuser=True` e `is_active=True`, e passa a
ser aceito pela `IsAdminRole` automaticamente — **sem precisar entrar no grupo
`admin`**.

**Anatomia do superuser vs. o `demo_admin`:**

| | `demo_admin` (seed) | superuser (`createsuperuser`) |
| --- | --- | --- |
| `is_staff` | sim | sim |
| `is_superuser` | não | **sim** |
| Grupo `admin` | sim | não (desnecessário) |
| `PUT`/`PATCH`/`DELETE` na API | permitido | permitido |
| Django Admin — *Items*, *Categories* | permitted | permitido |
| Django Admin — *Usuários*, *Grupos* | **negado** | **permitido** |

### 6.3 Opção C — `createsuperuser` não interativo

Útil para automação (CI/CD, provisionamento de ambiente). Exige `--username`
junto com `--noinput`, e a senha vem da variável
`DJANGO_SUPERUSER_PASSWORD`:

```bash
docker compose exec -e DJANGO_SUPERUSER_PASSWORD='SenhaForte@2026' `
  api python api/manage.py createsuperuser --noinput --username admin --email admin@synapseshop.local
```

Se o e-mail for omitido, o Django apenas avisa e segue.

### 6.4 Opção D — promover um usuário existente a superuser

```bash
docker compose exec api python api/manage.py shell -c "from django.contrib.auth import get_user_model; u = get_user_model().objects.get(username='demo_admin'); u.is_superuser = True; u.is_staff = True; u.save(update_fields=['is_superuser','is_staff']); print(u.username, '-> superuser:', u.is_superuser)"
```

> **Somente elevate a superuser em desenvolvimento.** Um superuser ignora
> toda verificação de permissão do Django Admin e da `IsAdminRole`.

### 6.5 Confirmar que o admin foi criado

Superusers (o comando 6.4 acrescenta o `demo_admin` a esta lista):

```bash
docker compose exec api python api/manage.py shell -c "from django.contrib.auth import get_user_model as G; print('SUPERUSERS:', list(G().objects.filter(is_superuser=True).values_list('username', flat=True)) or 'nenhum')"
```

Usuários com o papel `admin` (grupo homônimo):

```bash
docker compose exec api python api/manage.py shell -c "from django.contrib.auth import get_user_model as G; print('PAPEL ADMIN:', list(G().objects.filter(groups__name='admin').values_list('username', flat=True)))"
```

E faça login para provar que o token foi emitido:

```powershell
$body = @{ username = 'admin'; password = 'SenhaForte@2026' } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/auth/token/' -Method Post -ContentType 'application/json' -Body $body
```

---

## 7. Criar um usuário comum do zero

Como não existe endpoint de cadastro, use uma destas três formas.

### 7.1 Shell do Django (cria usuário **e** já atribui o grupo)

```bash
docker compose exec api python api/manage.py shell -c "from django.contrib.auth import get_user_model; from django.contrib.auth.models import Group; User = get_user_model(); u, criado = User.objects.get_or_create(username='cliente1', defaults={'email': 'cliente1@exemplo.com', 'first_name': 'Ana', 'last_name': 'Souza'}); u.set_password('SenhaForte@2026'); u.is_active = True; u.save(); u.groups.set([Group.objects.get(name='user')]); print('criado' if criado else 'atualizado', '->', u.username, list(u.groups.values_list('name', flat=True)))"
```

Saída: `criado -> cliente1 ['user']`

Esse usuário poderá fazer `POST`, mas receberá **403** em `PUT`/`PATCH`/`DELETE`.

Para criar direto no grupo `admin` (usuário interno), troque
`Group.objects.get(name='user')` por `Group.objects.get(name='admin')` e
acrescente `u.is_staff = True`.

### 7.2 Django Admin (interface web)

1. Faça login em `http://localhost:8000/admin/` com um superuser
   (veja a seção [9](#9-django-admin-em-admin)).
2. Menu **Authentication and Authorization** → **Users** → **Add user**.
3. Preencha `Username` e `Password`, marque **Active** e **Staff** apenas se
   precisar do Admin.
4. Salve. Depois, na página do usuário, abra o campo **Groups** e selecione
   `admin` ou `user`.
5. Salve novamente.

### 7.3 Reexecutando o `seed_auth` com outros nomes

```bash
docker compose exec -e SEED_USER_USERNAME=cliente1 -e SEED_USER_PASSWORD='SenhaForte@2026' `
  api python api/manage.py seed_auth
```

Mantém `demo_admin`/`demo_user` e adiciona o novo usuário no grupo `user`.

---

## 8. Promover, rebaixar, resetar senha e desativar

Todos via shell do Django. O `u.groups.set([...])` **substitui** a lista
inteira de grupos — passe todos os grupos que o usuário deve manter.

### 8.1 Promover para administrador (papel `admin`)

```bash
docker compose exec api python api/manage.py shell -c "from django.contrib.auth import get_user_model; from django.contrib.auth.models import Group; u = get_user_model().objects.get(username='cliente1'); u.groups.set([Group.objects.get(name='admin')]); print(u.username, '->', list(u.groups.values_list('name', flat=True)))"
```

Depois disso, `cliente1` já responde 200 em `PATCH`/`DELETE`.

### 8.2 Resetar senha

```bash
docker compose exec api python api/manage.py shell -c "from django.contrib.auth import get_user_model; u = get_user_model().objects.get(username='cliente1'); u.set_password('NovaSenha@2026'); u.save(); print('senha de', u.username, 'atualizada')"
```

> Use sempre `set_password()` + `save()`. **Nunca** escreva o hash direto no
> banco: `set_password` é quem gera o hash com o algoritmo configurado
> (PBKDF2 por padrão). `createsuperuser` interativo também serve para trocar a
> senha de um superuser existente.

### 8.3 Rebaixar (remover o papel `admin`)

```bash
docker compose exec api python api/manage.py shell -c "from django.contrib.auth import get_user_model; from django.contrib.auth.models import Group; u = get_user_model().objects.get(username='cliente1'); u.groups.set([Group.objects.get(name='user')]); print(u.username, '->', list(u.groups.values_list('name', flat=True)))"
```

Para **remover o acesso ao Django Admin** de um `staff`, use:

```bash
docker compose exec api python api/manage.py shell -c "from django.contrib.auth import get_user_model; u = get_user_model().objects.get(username='demo_admin'); u.is_staff = False; u.save(update_fields=['is_staff']); print(u.username, '-> staff:', u.is_staff)"
```

> Cuidado: rebaixar **não** remove `is_superuser`. Um superuser continua
> passando pela `IsAdminRole` mesmo fora do grupo `admin`. Para tirar o poder
> de superuser: `is_superuser = False` **e** `save()`.

### 8.4 Desativar um usuário (sem apagar)

`is_active = False` faz o login devolver 401 e bloqueia a API, mas preserva o
histórico:

```bash
docker compose exec api python api/manage.py shell -c "from django.contrib.auth import get_user_model; u = get_user_model().objects.get(username='cliente1'); u.is_active = False; u.save(update_fields=['is_active']); print(u.username, '-> ativo:', u.is_active)"
```

Reativar é o mesmo comando com `u.is_active = True`.

### 8.5 Excluir definitivamente

```bash
docker compose exec api python api/manage.py shell -c "from django.contrib.auth import get_user_model; n, _ = get_user_model().objects.get(username='cliente1').delete(); print('removido:', n)"
```

### 8.6 Criar um grupo novo

```bash
docker compose exec api python api/manage.py shell -c "from django.contrib.auth.models import Group; g, criado = Group.objects.get_or_create(name='gerente'); print('criado' if criado else 'ja existia', '->', g.name)"
```

Só o grupo `admin` tem efeito nas regras de acesso da Aula 7 — `IsAdminRole`
filtra por `name="admin"`. Grupos extras servem para organizar, mas não liberam
nada sozinhos.

---

## 9. Django Admin em `/admin/`

Interface web do Django, registrada em `api/config/urls.py`. Usa **sessão**
(cookie), não JWT — é o mesmo login de sempre do Django.

Requisitos: `is_active = True` **e** `is_staff = True`.

```bash
# 1) confirme o acesso
curl -I http://localhost:8000/admin/     # 302 -> /admin/login/?next=/admin/

# 2) faça login com um superuser (recomendado) ou com demo_admin
```

| Usuário | Entra no `/admin/`? | Telas de *Usuários*/*Grupos* |
| ------- | ------------------- | ------------------------------ |
| `demo_admin` | sim (`is_staff=True`) | **não** — não é superuser |
| superuser criado na [6.2](#62-opção-b--createsuperuser-interativo) | sim | sim |

### Login pelo navegador

1. Abra `http://localhost:8000/admin/`.
2. Entre com **Username** e **Password** (`demo_admin` /
   `demo-admin@Synapse2026`, ou o superuser que você criou).
3. O Admin lista **Authentication and Authorization** (Users, Groups) e
   **Core** (Categories, Items) — os dois últimos registrados em
   `api/core/admin.py`.

### Login por script (PowerShell)

```powershell
$s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$null = Invoke-WebRequest -Uri 'http://localhost:8000/admin/login/?next=/admin/' -Method Get -WebSession $s -UseBasicParsing
$r = Invoke-WebRequest -Uri 'http://localhost:8000/admin/login/?next=/admin/' -Method Post -WebSession $s -UseBasicParsing -MaximumRedirection 5 -Body @{
  username = 'demo_admin'; password = 'demo-admin@Synapse2026'; next = '/admin/'
  csrfmiddlewaretoken = $s.Cookies.GetCookies('http://localhost:8000')['csrftoken'].Value
}
$r.StatusCode   # 200, já autenticado
```

> O `GET` antes do `POST` não é opcional: é ele que deposita o cookie
> `csrftoken`. Sem ele, o Django responde **403 Forbidden**.

---

## 10. Troubleshooting

> As mensagens do DRF e do SimpleJWT saem **traduzidas** porque o projeto define
> `LANGUAGE_CODE = "pt-br"` em `api/config/settings.py`. Se você encontrar os
> textos em inglês, é sinal de que o `Accept-Language` foi sobreposto ou de que
> a tradução não foi carregada.

| Sintoma | Causa provável | Solução |
| ------- | -------------- | ------- |
| **401** `As credenciais de autenticação não foram fornecidas.` | Chamada de escrita sem header `Authorization` | `Authorization: Bearer <access>` |
| **401** `O token informado não é válido para qualquer tipo de token` | `access` expirado (passou dos **5 minutos**), adulterado ou emitido com outra `JWT_SIGNING_KEY` | Refaça o login ou use `/auth/token/refresh/` com o `refresh` |
| **401** `Usuário e/ou senha incorreto(s)` no login | Senha trocada, ou usuário desativado (`is_active=False`) | Reative com `is_active = True` ([8.4](#84-desativar-um-usuário-sem-apagar)) e resete a senha ([8.2](#82-resetar-senha)) |
| **403** `Ação restrita ao papel 'admin'.` | Autenticado, mas sem grupo `admin` e sem `is_superuser` | Promova com [8.1](#81-promover-para-administrador-papel-admin) |
| **403 Forbidden** ao fazer login no `/admin/` | POST sem o cookie `csrftoken` (não fez o GET antes) | Faça o GET da página de login antes ([9](#9-django-admin-em-admin)) |
| **429** `Request was throttled` | Mais de 5 logins/refreshes por minuto | Aguarde ~1 min; a cota é `login: 5/min` em `settings.py` |
| **404** `No Category matches the given query.` | O `id` da URL não existe. Cada ambiente tem ids próprios — aqui o `id=1` já foi removido nos testes da Aula 7 | Liste antes e use o id retornado: `?page_size=1` e depois `$cat.results[0].id` |
| **400** `JSON parse error` no `curl.exe` do PowerShell | Aspas do JSON mastigadas pelo PowerShell | Use `ConvertTo-Json` ([3.1](#31-login-powershell)) |
| Response mostra `EletrÃ´nicos` mas o banco está correto | **Não é bug do servidor.** O DRF responde `Content-Type: application/json` **sem `charset`**, e o `Invoke-RestMethod` do PowerShell 5.1 cai em Windows-1252 na hora de decodificar a resposta | Bytes no servidor estão certos. Leia os bytes crus com `[System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())`, ou use `curl.exe` |
| **`could not translate host name "db"`** | Rodou `manage.py` no `.venv` com a `DATABASE_URL` do compose | Remonte a `DATABASE_URL` com `localhost:5432` ([5.2](#52-pelo-django-no-venv-local)) |
| `CommandError: You must use --username with --noinput` | Faltou `--username` no `createsuperuser --noinput` | Veja [6.3](#63-opção-c--createsuperuser-não-interativo) |
| `CommandError: Superusers must have a password` | Faltou `DJANGO_SUPERUSER_PASSWORD` no `--noinput` | Passe a variável com `docker compose exec -e` |
| Cria o usuário mas o login continua 401 | `set_password` chamado **sem** `save()` | Sempre `set_password()` seguido de `save()` |
| `seed_auth` roda mas a senha do `.env` não é aplicada | `SEED_*` não é injetado pelo Compose, e o comando só seta a senha **na criação** | Use `-e` ao executar, ou resete a senha via [8.2](#82-resetar-senha) |

---

## 11. Checklist rápido de validação

Coleção Postman pronta: `collections/synapseshop_aula7.postman_collection.json`
(variáveis `base_url`, `token_admin`, `token_user`, `refresh_admin`).

```powershell
# 1) ambiente no ar
Invoke-RestMethod http://localhost:8000/health

# 2) login como admin -> 200 e par de tokens
$t = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/auth/token/' -Method Post -ContentType 'application/json' -Body (@{ username='demo_admin'; password='demo-admin@Synapse2026' } | ConvertTo-Json -Compress)
$h = @{ Authorization = "Bearer $($t.access)" }

# 3) rota administrativa com admin -> 200
#    (pegue um id que exista: os ids do banco variam entre ambientes)
$cat = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/categories/?page_size=1' -Headers $h
$id  = $cat.results[0].id
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/categories/$id/" -Method Patch -Headers $h -ContentType 'application/json' -Body (@{ description='atualizado' } | ConvertTo-Json -Compress)

# 4) login como user -> 200
$u = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/auth/token/' -Method Post -ContentType 'application/json' -Body (@{ username='demo_user'; password='demo-user@Synapse2026' } | ConvertTo-Json -Compress)

# 5) mesma rota com user -> 403
try { Invoke-RestMethod -Uri "http://localhost:8000/api/v1/categories/$id/" -Method Patch -Headers @{ Authorization = "Bearer $($u.access)" } -ContentType 'application/json' -Body (@{ description='x' } | ConvertTo-Json -Compress) } catch { "esperado 403 -> $($_.Exception.Response.StatusCode.value__)" }

# 6) refresh -> novo access 200
(Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/auth/token/refresh/' -Method Post -ContentType 'application/json' -Body (@{ refresh=$t.refresh } | ConvertTo-Json -Compress)).access
```

Matriz de status esperada:

| Cenário | Status |
| ------- | ------ |
| Healthcheck | 200 |
| Login admin / user (credenciais corretas) | 200 |
| Login com credencial errada | 401 |
| `refresh` / `verify` | 200 |
| `GET` list/detail sem token | 200 |
| `POST` sem token | 401 |
| `POST` com user / admin | 201 |
| `PUT`/`PATCH`/`DELETE` com user | 403 |
| `PUT`/`PATCH` com admin | 200 |
| `DELETE` com admin | 204 |
| Burst de login (>5/min) | 429 |
| Página de listagem inexistente | 404 |

---

## Referências

- Código: `api/core/urls.py` (rotas de token),
  `api/core/permissions.py` (`IsAdminRole`),
  `api/core/management/commands/seed_auth.py` (papéis e usuários demo),
  `api/config/settings.py` (`REST_FRAMEWORK`, `SIMPLE_JWT`, throttles).
- Collection Postman: `collections/synapseshop_aula7.postman_collection.json`.
- Visão geral do projeto: [README.md](README.md).
