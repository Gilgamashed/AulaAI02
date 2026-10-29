# Spec: Gate de Tipagem Estático Realmente Verde (Fix01)

## 1. Objetivo

Tornar o gate de tipagem do SynapseShop **reproduzível e verde**, de modo que
`mypy api services dashboard` termine com código de saída `0` e passe a ser um
critério real de entrega — sem suprimir a checagem de código do projeto e sem
introduzir funcionalidades de aulas posteriores.

Esta é uma spec de **manutenção** (Fix01), não uma aula do curso. Ela resolve a
dívida identificada na validação da Aula 21.

## 2. Contexto e diagnóstico

Em 2026-10-28, com `mypy 2.3.1` e o venv local, o comando previsto no
`AGENTS.md`:

```bash
python -m mypy api services dashboard
```

produzia **129 erros em 49 arquivos**. A investigação mostrou três causas
distintas:

| Causa | Erros | Natureza |
| --- | ---: | --- |
| Stubs/importação de terceiros ausentes (`django`, `rest_framework`, `pika`, `streamlit`, `pandas`, `django_filters` etc.) | 117 | ruído de ambiente |
| Resolução de pacotes (`core`, `config`, `app`) sem raiz explícita | incluído acima | configuração |
| Erros reais de tipagem em código das aulas anteriores | 12 | dívida de tipos |

Com as flags que corrigem ambiente e resolução:

```bash
python -m mypy --ignore-missing-imports --explicit-package-bases api services dashboard
```

o resultado cai para **12 erros em 6 arquivos**, nenhum deles nos módulos da
Aula 21. Esses 12 erros são o escopo de correção desta spec.

### Princípio

O gate não pode ser "verde" por omissão global de erros. A configuração pode
ignorar **bibliotecas de terceiros sem stubs**, mas não pode ignorar módulos
do próprio projeto, arquivos inteiros ou códigos de erro genéricos.

## 3. Escopo

### Incluído

- Configuração `[tool.mypy]` na raiz (`pyproject.toml`).
- Inclusão do `mypy` no `requirements-dev.txt` e, portanto, na imagem de teste.
- Correção dos 12 erros reais listados na seção 5.3.
- Definição de um comando canônico, reproduzível no host e no container.
- Atualização de `AGENTS.md`, `README.md`, `specs/README.md`,
  `docs/CHANGELOG.md` e `PROMPTS.md`.

### Excluído

- Instalar `django-stubs`/`djangorestframework-stubs` ou habilitar o plugin do
  Django. Isso é uma evolução futura, com escopo maior.
- Ativar `disallow_untyped_defs`, `check_untyped_defs` ou novas regras que
  gerem uma segunda leva de erros.
- Alterar contratos HTTP, eventos, modelos, migrações de produto ou
  comportamento em runtime.
- Refatorações estéticas nos arquivos de mensageria/Alembic além do necessário
  para tipar corretamente.
- Corrigir erros de tipagem que não estejam entre os 12 mapeados (se surgirem,
  registrar como nova dívida, não esconder).
- Alterar `docs/openapi.yaml`, salvo se outra tarefa tocar no contrato.

## 4. Configuração obrigatória

### 4.1 `pyproject.toml` (raiz)

Adicionar:

```toml
[tool.mypy]
python_version = "3.12"
explicit_package_bases = true
ignore_missing_imports = true
show_error_codes = true
warn_unused_configs = true
```

Justificativa:

- `explicit_package_bases`: faz `api/core` ser o módulo `core` e
  `api/config` ser `config`, em vez de `api.core`/`api.config`. Sem isso, os
  imports internos (`from core.llm import ...`) não resolvem.
- `ignore_missing_imports`: bibliotecas sem stubs (`django`, `rest_framework`,
  `pika`, `streamlit`, `pandas` etc.) passam a ser `Any`. É a fronteira
  consciente desta opção; o código do projeto continua checado.
- `show_error_codes`: torna explícito o código de cada erro, necessário para
  `# type: ignore[codigo]` localizado, se for o caso.
- `warn_unused_configs`: denuncia configuração morta.

**Não usar** `disable_error_code` global, `ignore_errors = true` por módulo,
`follow_imports = "skip"` nem exclusão de `api/`, `services/` ou `dashboard/`.

### 4.2 `requirements-dev.txt`

Adicionar, com comentário justificando o pin:

```text
# Tipagem estática (Fix01). Pin exato: versões novas do mypy podem introduzir
# checagens que quebram o gate sem nenhuma mudança de código.
mypy==2.3.1
```

O pin deve ser o mesmo usado para deixar o gate verde. Atualizações futuras do
mypy são uma tarefa deliberada, com nova rodada de correções.

### 4.3 Comando canônico

Adotar e documentar:

```bash
# Host (venv)
python -m mypy api services dashboard

# Container de testes (imagem com requirements-dev)
docker compose run --rm tests python -m mypy api services dashboard
```

O comando do container é o gate oficial, porque não depende do venv de quem
executa.

## 5. Tarefas e responsabilidades

### 5.1 Configuração e toolchain

- [ ] Adicionar `[tool.mypy]` ao `pyproject.toml` conforme a seção 4.1.
- [ ] Adicionar `mypy==2.3.1` ao `requirements-dev.txt`.
- [ ] Rebuildar a imagem de teste: `docker compose build tests`.
- [ ] Confirmar `mypy --version` dentro do container.
- [ ] Atualizar o `AGENTS.md`:
  - comando de qualidade passa a ser
    `docker compose run --rm tests python -m mypy api services dashboard`;
  - item 3 da validação obrigatória passa a citar o mesmo comando e "zero
    erros", eliminando a divergência atual entre `mypy api services` e
    `mypy api services dashboard`.
- [ ] Adicionar uma seção curta no `README.md` ("Qualidade / tipagem") com o
  comando e a política de `ignore_missing_imports`.

### 5.2 Correções dos 12 erros

Cada correção deve preservar o comportamento em runtime. Tipos devem descrever
o contrato real; `cast` só é aceitável quando o runtime já validou o tipo.

| # | Arquivo:linha | Erro | Correção obrigatória |
| --- | --- | --- | --- |
| 1 | `api/core/migrations/0001_initial.py:12` | `Need type annotation for "dependencies"` | Anotar `dependencies: list[tuple[str, str]] = []`. |
| 2 | `api/config/settings_test.py:66` | `DEDUPE_TTL_SEGUNDOS` usado antes da definição (vem de `from .settings import *`) | Referenciar explicitamente o módulo: `from . import settings as _settings` e usar `_settings.DEDUPE_TTL_SEGUNDOS`; ou import explícito do nome. Não usar `# type: ignore`. |
| 3 | `api/core/messaging/kafka_admin.py:378` / `:401` | `int - None` porque `particoes` é inferido como `list[dict[str, int \| None]]` | Anotar `particoes: list[dict[str, Any]] = []` (ou tipar explicitamente o retorno de `get_watermark_offsets` como `tuple[int, int]`). Não alterar a lógica de offsets. |
| 4 | `api/core/messaging/kafka_consumidor.py:867` | `PedidoCriado \| PagamentoRegistrado` passado a `evento: PedidoCriado` | Ampliar `_reentregar_ou_dlq` para `evento: PedidoCriado \| PagamentoRegistrado`; o método já usa `_registrar_falha`, que aceita a união, e ambos os eventos têm `pedido_id`. |
| 5 | `api/core/messaging/kafka_consumidor.py:656` e `:710` | Handlers tipados para um tipo concreto recebem a união do dispatch | Ampliar `_aplicar_efeito_pedido` e `_aplicar_efeito_pagamento` para aceitar `PedidoCriado \| PagamentoRegistrado`, mantendo os `isinstance` internos que já validam o fluxo. Alternativa aceitável: `cast` no dispatch após a validação, mas a assinatura ampliada é preferível por refletir o contrato real. |
| 6 | `api/core/management/commands/inspecionar_dlq_kafka.py:130` | `.decode()` em `bytes \| None` porque `mensagem.key()` é chamado duas vezes | Guardar `chave = mensagem.key()` numa variável local e usar `chave.decode(...) if chave else None`. O runtime já era seguro; a correção é só de narrowing. |
| 7 | `services/inventory/alembic/env.py:31`, `:52`, `:71` | `include_object` com assinatura mais estreita que `Callable[[SchemaItem, str \| None, Literal[...], bool, SchemaItem \| None], bool]` | Anotar `obj: SchemaItem`, `name: str \| None`, `compare_to: SchemaItem \| None` e `type_` com um `Literal` dos sete valores aceitos (`schema`, `table`, `column`, `index`, `unique_constraint`, `foreign_key_constraint`, `check_constraint`). Se a assinatura de versão do Alembic impedir, aplicar `# type: ignore[arg-type]` **somente** nas duas chamadas `context.configure`, com comentário justificando. |

Total: **12 erros** — 4 em `kafka_admin.py`, 3 em `kafka_consumidor.py`, 2 em
`alembic/env.py`, 1 em `settings_test.py`, 1 em `inspecionar_dlq_kafka.py` e
1 na migração.

### 5.3 Política de supressões

- `# type: ignore` só é permitido quando o tipo não puder ser expresso sem
  alterar comportamento, sempre com **código específico** (`# type: ignore[arg-type]`)
  e comentário de uma linha explicando o motivo.
- Proibido `# mypy: ignore-errors`, `ignore_errors = true` por módulo e
  `disable_error_code` global.
- Revisar o diff para garantir que nenhuma supressão nova foi adicionada além
  das exceções acima.
- Se um erro novo aparecer fora dos 12, a tarefa deve ser interrompida e o erro
  documentado como dívida separada — não mascarado.

### 5.4 Documentação e rastreabilidade

- [ ] Atualizar `AGENTS.md` (comando e critério de aceite).
- [ ] Atualizar `README.md` com a seção de tipagem.
- [ ] Adicionar a linha `Fix01` em `specs/README.md`.
- [ ] Registrar em `docs/CHANGELOG.md` uma entrada de manutenção
  (`[1.21.1] - 2026-10-28` ou a versão vigente) com:
  - configuração do mypy;
  - pin do mypy no `requirements-dev.txt`;
  - correção dos 12 erros;
  - comando canônico.
- [ ] Registrar em `PROMPTS.md` o uso de IA para elaborar/executar esta spec,
  incluindo o diagnóstico 129 → 12 → 0.

## 6. Definition of Done

- [ ] `[tool.mypy]` presente na raiz com a configuração da seção 4.1.
- [ ] `mypy==2.3.1` instalado pela imagem de teste.
- [ ] Os 12 erros corrigidos sem alterar o comportamento em runtime.
- [ ] Nenhuma supressão global ou por arquivo inteiro; `# type: ignore` apenas
  localizado e justificado, se houver.
- [ ] `python -m mypy api services dashboard` → **0 erros**.
- [ ] `docker compose run --rm tests python -m mypy api services dashboard`
  → **0 erros**.
- [ ] `ruff check .` → sem erros.
- [ ] `docker compose run --rm tests` → suíte completa verde, cobertura
  `>= 85%` (baseline atual: 398 testes / 89,64%).
- [ ] Nenhum contrato HTTP, evento, migração de produto ou comportamento
  alterado.
- [ ] `AGENTS.md`, `README.md`, `specs/README.md`, `docs/CHANGELOG.md` e
  `PROMPTS.md` atualizados.
- [ ] Diff restrito a configuração, dependências, 6 arquivos de código e
  documentação.

## 7. Validação

### 7.1 Baseline (antes)

```bash
python -m mypy api services dashboard
# 129 erros (117 de stubs/importação + 12 reais)

python -m mypy --ignore-missing-imports --explicit-package-bases api services dashboard
# 12 erros em 6 arquivos
```

### 7.2 Gate final (depois)

```bash
docker compose build tests
docker compose run --rm tests python -m mypy --version
docker compose run --rm tests python -m mypy api services dashboard
docker compose run --rm tests ruff check .
docker compose run --rm tests
```

Resultados esperados:

```text
mypy 2.3.1
Success: no issues found in 107 source files
All checks passed!
398 passed, ... coverage 89.64%
```

O número de fontes e de testes pode variar; o critério é **zero erros de mypy**
e suíte verde com cobertura `>= 85%`.

### 7.3 Verificações complementares

```bash
# Nenhuma supressão global nova
grep -R "ignore-errors\|disable_error_code\|ignore_errors" pyproject.toml api services dashboard

# Nenhum type: ignore sem código
grep -R "# type: ignore" api services dashboard | grep -v "\["

# Escopo do diff
git diff --stat
```

Se `docs/` ou `docs/openapi.yaml` forem alterados por outro motivo, rodar
também:

```bash
powershell -ExecutionPolicy Bypass -File scripts/lint-openapi.ps1
```

## 8. Riscos e mitigação

| Risco | Mitigação |
| --- | --- |
| Versão nova do mypy introduzir erros sem mudança de código | Pin exato `mypy==2.3.1`; atualização é tarefa separada. |
| `ignore_missing_imports` esconder uso incorreto de API de terceiro | Aceito conscientemente nesta opção; documentar como dívida e evoluir para stubs (`django-stubs`) depois. |
| Ampliar a união em `kafka_consumidor.py` mascarar um dispatch errado | Os handlers já têm `isinstance`; rodar os testes de fluxo de pedidos e pagamentos. |
| `settings_test` depende de `import *` | Usar referência explícita ao módulo; não remover o `import *` nesta tarefa (mudança maior). |
| Assinatura de `include_object` variar com a versão do Alembic | Validar com a versão fixada no `requirements.txt`; se necessário, `# type: ignore[arg-type]` localizado nas duas chamadas. |
| Dashboard não ter `streamlit`/`pandas` na imagem de teste | O `ignore_missing_imports` cobre a ausência; `dashboard/ask_sql.py` é stdlib. Se páginas gerarem ruído, avaliar exclusão justificada de `dashboard/pages/*`, sem excluir `dashboard/`. |
| Correções de tipo alterarem runtime | Mudanças limitadas a anotações, narrowing e referências explícitas; suíte completa obrigatória. |

## 9. Arquivos afetados

**Configuração/dependências**

- `pyproject.toml`
- `requirements-dev.txt`

**Código (somente tipagem)**

- `api/core/migrations/0001_initial.py`
- `api/config/settings_test.py`
- `api/core/messaging/kafka_admin.py`
- `api/core/messaging/kafka_consumidor.py`
- `api/core/management/commands/inspecionar_dlq_kafka.py`
- `services/inventory/alembic/env.py`

**Documentação**

- `AGENTS.md`
- `README.md`
- `specs/README.md`
- `docs/CHANGELOG.md`
- `PROMPTS.md`
- `specs/specs_da_aula_Fix01.md` (esta spec)

## 10. Evidências esperadas

- Saída do baseline: 129 erros; com flags: 12 erros.
- Saída final: `Success: no issues found`.
- `mypy --version` no container: `2.3.1`.
- `ruff check .`: `All checks passed!`.
- Suíte: 398+ testes, cobertura `>= 85%`.
- `git diff --stat` sem arquivos fora do escopo.
