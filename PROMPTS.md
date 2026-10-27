## [2026-10-23] Aula 19 - Conexão Segura, SQL Injection e Painel Streamlit

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec `specs/spec_da_aula_19.md` - implementar conexão segura com PostgreSQL (SSL/TLS, pooling, timeouts), mitigar SQL Injection com consultas parametrizadas e allow-list, criar painel Streamlit com filtros/cache, integrar ao Docker Compose com live reload e TLS no banco.
- **Prompt:** "vamos prosseguir agora com a realização de todas as tarefas e responsabilidades do @specs/spec_da_aula_19.md para validação pelo DoD. podemos incluir testes agora. não commitar por enquanto. lembrando que estou usando o windows powershell, por isso comandos como 'tail' e 'head' não funcionam e geram erro. utilize comandos nativos do powershell."
- **Resultado/Decisão:** Criado `dashboard/` com `db.py`, `security.py`, `queries.py`, `simular_sqli.py`, `app.py`, Dockerfile e config. Adicionado TLS ao PostgreSQL via `docker/postgres/`. Atualizados `docker-compose.yml`, `api/config/settings.py`, `services/inventory/app/config.py`, `services/inventory/app/database.py`. Removidos módulos parciais `api/core/db/` e `scripts/db/`. Criados testes unitários para conexão segura, consultas parametrizadas, simulação SQLi e inventory. Atualizados `README.md`, `docs/aulas/19-dashboard.md`, `docs/CHANGELOG.md`, `specs/README.md`, `AGENTS.md`, `pyproject.toml` e `.env.example`.
- **Revisão humana/ajuste manual:** Zero interpolação de strings em SQL, ordenação restrita a allow-list, uso exclusivo de bind parameters, `DB_SSLMODE=require` no compose, cache `@st.cache_data(ttl=60)` e bind-mount com live reload. Não commitado conforme solicitado.

## [2026-10-27] Aula 20 - Dashboard de Desempenho da API em Streamlit

- **Ferramenta:** opencode (opencode/big-pickle) e OpenCode (DeepSeek V4.1 Flash) na revisão/correção.
- **Contexto:** Spec `specs/spec_da_aula_20.md` - criar painel de observabilidade/desempenho com KPIs, latência/p95, throughput, distribuição por status code, filtros interativos, cache, integração ao Docker Compose.
- **Prompt 1 (implementação inicial):** "vamos prosseguir agora com a realização de todas as tarefas e responsabilidades do @specs/spec_da_aula_20.md para validação pelo DoD. vamos seguir a spec para que os itens do DoD sejam concluidos."
- **Prompt 2 (revisão do DoD):** "Poderia verificar se está tudo ok e se o DoD pode ser considerado done, e a documentação readme e prompts estao ok, e se os commits estão ok".
- **Prompt 3 (correção + opcionais):** "Vamos executar esse plano e tratar também dos itens opcionais".
- **Resultado/Decisão:**
  - Middleware `core.observability.RegistrarMetricasMiddleware` com latência, normalização de IDs/UUIDs e instrumentação restrita a `/api/` (`/health`, `/admin`, `/static` e docs ficam de fora para não distorcer a amostra).
  - Modelo `RequisicaoMetrica` + migração `0006_requisicaometrica`; retenção por `manage.py limpar_metricas --dias N [--dry-run]`.
  - **Hit rate real de cache:** janela por thread em `core.cache_metrics`, aberta/fechada pelo middleware e gravada em `cache_hits`/`cache_misses`/`cache_bypasses`. Bypass não entra no denominador.
  - Página multipage `dashboard/pages/2_Desempenho_da_API.py` com KPIs, throughput/latência por hora, distribuição **por classe** 2xx/3xx/4xx/5xx (com detalhe por código), requisições por endpoint, filtros de período/endpoint/classe e `@st.cache_data(ttl=60)`.
  - Bloco de pedidos por status rotulado como estado persistido (`core_pedido`), não como profundidade de fila do broker.
  - README (subida, acesso, tráfego, toggle e retenção), `docs/aulas/20-desempenho.md`, `docs/CHANGELOG.md`, `specs/README.md` e `.env.example` atualizados.
- **Revisão humana/ajuste manual:** a primeira versão havia sobrescrito `api/core/models.py` e `api/core/serializers.py` com uma variante antiga do domínio (sem `idempotency_key`, `slug`, `is_active`, estados do pagamento e `CANAL_CHOICES`), o que quebrava `manage.py check` e a coleta da suíte. Ambos foram restaurados do HEAD e a Aula 20 reaplicou somente `RequisicaoMetrica`. Também foram corrigidos o gráfico de status (classes em vez de códigos crus), a hit rate (medida em vez de proxy por latência) e a documentação de retenção.
