# BIMOFFICE Knowledge na nuvem — avaliação, arquitetura e implantação (v0.6)

## 1. Avaliação da arquitetura (antes desta etapa)

| Recurso | Antes (v0.5) | Problema para a nuvem |
|---|---|---|
| Banco | SQLite num arquivo local (~70 trechos de SQL específicos) | um único servidor, sem acesso simultâneo de vários serviços |
| Arquivos | pasta `data/` no disco do servidor | serviços de nuvem apagam o disco ao reiniciar |
| Processamento IFC | thread dentro da API | API e processamento disputam memória/CPU; não escala |
| Acesso | sem login (senha única opcional) | dados institucionais expostos na internet |
| Implantação | `iniciar.bat` no PC | sem imagem, sem verificação de saúde, sem backup testado |

## 2. O que foi feito (Etapa 1 — preparação da nuvem) — tudo testado

| Item | Como | Verificação |
|---|---|---|
| **PostgreSQL** (produção) | `BIMOFFICE_DATABASE_URL=postgresql://…`; camada que traduz o SQL; busca textual com `tsvector` + configuração `bimoffice` (unaccent) equivalente ao FTS5; migrações versionadas (`backend/database/migrations/`, tabela `schema_migrations`) | suíte inteira em PostgreSQL 16 |
| SQLite (local) | continua o padrão, sem mudança de comportamento | suíte inteira |
| **Armazenamento S3** | `backend/storage.py`: chave por hash; disco local (mesmas pastas de antes) ou S3 compatível (AWS, Google Cloud Storage, R2, MinIO…); download em partes | suíte com S3 simulado (moto) + testes dedicados |
| **Worker separado** | `python -m backend.worker`; fila no PostgreSQL com `FOR UPDATE SKIP LOCKED` (vários workers, cada tarefa uma vez); sinal de vida; retomada só de workers parados; tempo limite; tentativas | testes de concorrência real, processo separado, tempo limite |
| **Login e permissões** | papéis admin/editor/leitor; equipes por projeto (dono/editor/leitor); sessões com expiração; senha em hash scrypt; autorização central por rota; auditoria de todas as alterações e logins | 8 testes de isolamento entre equipes + navegador |
| **Docker** | `Dockerfile` (imagem única API/worker, modelo E5 embutido), `docker-compose.yml` (db, api, worker, s3 de teste), `.env.example` | imagem construída e ambiente completo validado no navegador (login → IFC no S3 → worker → memorial → permissões → auditoria → reinício sem perda) |
| **Saúde** | `/api/health` (vivo) e `/api/health/ready` (banco + armazenamento; 503 se falhar) | testes |
| **Backup/restauração** | `python -m backend.backup backup|restore` (banco + arquivos + manifesto SHA-256; confere integridade antes de restaurar; só restaura em banco vazio) | ida e volta completa em SQLite e PostgreSQL, disco e S3 |
| **Migração dos dados locais** | `python -m backend.backup migrar <bimoffice.db> <pasta data>` → PostgreSQL + S3 (ids preservados, sequências ajustadas) | teste SQLite → PostgreSQL |
| **CI** | `.github/workflows/testes-nuvem.yml`: suíte em PostgreSQL (disco e S3) + construção e subida da imagem | roda a cada envio |

### Decisões técnicas (justificadas)
- **Fila no PostgreSQL em vez de Redis + Celery.** O volume é baixo (dezenas de IFCs por dia, não milhares por
  minuto), o progresso/cancelamento/histórico já ficam no banco, e `SKIP LOCKED` dá a mesma garantia de
  "cada tarefa para um worker". É um serviço a menos para pagar, proteger e fazer backup. Se um dia houver
  milhares de tarefas por minuto, a interface `backend/jobs.py` permite trocar por Redis/RQ sem mudar o resto.
- **Vetores**: continuam em `BYTEA` + numpy (rápido até dezenas de milhares de trechos). **pgvector** foi
  avaliado: é o caminho quando a biblioteca passar de ~50–100 mil trechos (índice HNSW dentro do banco).
  Não foi ativado agora porque a extensão não existe neste ambiente de testes e não é necessária no volume atual.
- **Modelo de IA dentro da imagem** (`PRELOAD_MODEL=1`): início rápido e sem depender do Hugging Face
  em produção. Se o modelo faltar, a pesquisa avisa e usa só palavras, sem travar (falha lembrada por 5 min).
- **GitHub Pages** pode continuar servindo a interface; a própria API também serve a interface (mesmo endereço,
  sem CORS) — mais simples para o login.

## 3. Arquitetura alvo

```
 Navegador ──HTTPS──► API FastAPI (container)  ──► PostgreSQL gerenciado (backups automáticos do provedor)
                         │  login, permissões,        ▲
                         │  biblioteca, memoriais     │ fila de tarefas (SKIP LOCKED)
                         ▼                            │
                  Armazenamento de objetos ◄── Worker(s) (mesma imagem: python -m backend.worker)
                  (S3 compatível, versionado)          IfcOpenShell, limites de memória/CPU
```

## 4. Hospedagem — comparação (preços aproximados, nov/2026; confira antes de contratar)

Necessidade estimada: API ~2 GB de RAM (modelo E5 ~1 GB) · worker 2–4 GB (IFC grande) · PostgreSQL pequeno ·
dezenas de GB de arquivos. **Nenhum serviço foi contratado.**

| | A) Google Cloud (Cloud Run + Cloud SQL + Cloud Storage) | B) VPS único (ex.: Hetzner CX32) com docker-compose | C) Render (PaaS) |
|---|---|---|---|
| Região no Brasil | **sim (São Paulo)** — melhor para LGPD | não (Europa/EUA) | não |
| Computação | paga por uso; Cloud Run ~US$ 0,000018–0,000024 por vCPU·s e ~US$ 0,000002–0,0000025 por GiB·s, com cota gratuita mensal | 4 vCPU / 8 GB por ~US$ 8–9/mês | instâncias de 4 GB ~US$ 85/mês cada (API e worker) |
| Banco | Cloud SQL: db-f1-micro ~US$ 8–9/mês; db-g1-small ~US$ 26/mês | PostgreSQL no próprio servidor (backup por nossa conta) | Postgres ~US$ 19/mês (1 GB) |
| Arquivos | Cloud Storage (centavos por GB) | volume do servidor + cópia externa | disco ~US$ 0,25/GB ou S3 externo |
| Estimativa mensal | **~US$ 35–90** (uso moderado; depende de manter instância sempre ligada) | **~US$ 10–15** (+ tempo de manutenção) | **~US$ 190+** |
| Manutenção | baixa (serviços gerenciados) | alta (atualizações, segurança, backups do servidor) | baixa |
| Gemini / Drive | mesmo fornecedor (Google) | indiferente | indiferente |

**Recomendação:** **A) Google Cloud na região São Paulo**, para dados institucionais (LGPD, backups gerenciados,
mesmo ecossistema do Gemini e do Google Drive, pouca manutenção). **B)** é a alternativa de menor custo se houver
quem administre o servidor. Antes de decidir, vale consultar a TI do SENAI (pode haver contrato/infra existente).

Fontes de preço (terceiros, conferir na página oficial): [Render](https://www.srvrlss.io/provider/render/),
[Render 2026](https://temps.sh/blog/render-pricing-2026), [Cloud Run](https://www.usage.ai/blogs/gcp/cloud-run-pricing/),
[Cloud SQL db-g1-small](https://www.bytebase.com/dbcost/cloudsql/instance/db-g1-small/),
[Postgres 2026](https://www.bytebase.com/blog/postgres-hosting-options-pricing-comparison/),
[Hetzner CX32](https://www.vpsbenchmarks.com/hosters/hetzner/plans/cx32), [Hetzner 2026](https://kuberns.com/blogs/hetzner-cloud-pricing/).

## 5. Implantação (quando aprovada)

### Opção A — Google Cloud (resumo)
1. Projeto no Google Cloud, região `southamerica-east1`; ativar Cloud Run, Cloud SQL, Cloud Storage, Artifact Registry.
2. Cloud SQL PostgreSQL 16 (com backups automáticos e recuperação pontual); criar banco `bimoffice`.
3. Bucket no Cloud Storage com **versionamento** ativado; chave HMAC para acesso S3
   (`BIMOFFICE_S3_ENDPOINT_URL=https://storage.googleapis.com`).
4. Construir e enviar a imagem: `docker build -t <região>-docker.pkg.dev/<projeto>/bimoffice/app .`
5. Serviço Cloud Run **api** (2 GiB, porta 8000, `BIMOFFICE_JOB_WORKER=0`) e serviço **worker**
   (comando `python -m backend.worker`, 4 GiB, mínimo 1 instância, CPU sempre alocada).
6. Segredos (senha do banco, chaves S3, senha inicial do admin) no **Secret Manager**, nunca no repositório.
7. `BIMOFFICE_AUTH=on`, `BIMOFFICE_ADMIN_EMAIL/PASSWORD` (1ª vez), `BIMOFFICE_CORS_ORIGINS` com o endereço do Pages.

### Opção B — servidor com docker-compose
```
git clone https://github.com/brunno100barros-del/BIMOFFICE-Knowledge && cd BIMOFFICE-Knowledge
cp .env.example .env      # preencher senhas
docker compose up -d --build
```
Colocar um proxy HTTPS na frente (ex.: Caddy) e agendar o backup (seção 6).

### Variáveis de ambiente
| Variável | Uso |
|---|---|
| `BIMOFFICE_DATABASE_URL` | `postgresql://usuario:senha@host:5432/bimoffice` (vazio = SQLite local) |
| `BIMOFFICE_STORAGE`, `BIMOFFICE_S3_BUCKET`, `BIMOFFICE_S3_ENDPOINT_URL`, `BIMOFFICE_S3_REGION`, `BIMOFFICE_S3_PREFIX` | arquivos em S3; credenciais em `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` |
| `BIMOFFICE_AUTH`, `BIMOFFICE_SESSION_HOURS`, `BIMOFFICE_ADMIN_EMAIL`, `BIMOFFICE_ADMIN_PASSWORD` | login |
| `BIMOFFICE_JOB_WORKER`, `BIMOFFICE_JOB_TIMEOUT_SECONDS`, `BIMOFFICE_JOB_STALE_SECONDS` | processamento |
| `BIMOFFICE_MAX_IFC_MB`, `BIMOFFICE_IFC_GEOMETRY_SECONDS` | limites |
| `BIMOFFICE_CORS_ORIGINS`, `BIMOFFICE_API_TOKEN` | acesso pela web / acesso de serviço |
| `BIMOFFICE_MODELS_DIR` | pasta do modelo de IA (na imagem: `/opt/bimoffice-modelos`) |

## 6. Backup, restauração e migração
```
python -m backend.backup backup /caminho/backups        # banco + arquivos + manifesto (SHA-256)
python -m backend.backup restore /caminho/backups/bimoffice_backup_AAAAMMDD_HHMMSS   # em banco VAZIO
python -m backend.backup migrar data/database/bimoffice.db data   # do PC (SQLite) para a nuvem
```
Na nuvem: backups automáticos do banco (provedor) + versionamento do bucket + este backup agendado (diário) para
outro local. **Teste de restauração** recomendado mensalmente (o procedimento é o mesmo dos testes automáticos).

## 7. Situação em relação aos critérios de conclusão do pedido

| # | Critério | Situação |
|---|---|---|
| 1 | Endereço web seguro | **pendente** — depende da contratação aprovada por você |
| 2 | Sem servidor no seu PC | arquitetura pronta e testada em containers; **falta implantar** |
| 3 | Upload e processamento IFC na nuvem | **pronto e testado** (API + worker + S3 em containers) |
| 4–5 | Visualização 3D, seleção, propriedades | **próxima etapa** |
| 6–7 | Capítulos ↔ GlobalIds/versões; navegação bidirecional | **próxima etapa** |
| 8 | Busca, biblioteca, projetos, DOCX preservados | **sim** — suíte de regressão em SQLite e PostgreSQL |
| 9 | IA e Google Drive | **pendente** — dependem de chave/credenciais suas |
| 10 | Dados mantidos após reinicializações | **testado** (reinício de API, worker e banco sem perda) |
| 11 | Backup e restauração testados | **sim** (automatizado) |
| 12 | Testes de regressão | **sim** (4 combinações de banco × armazenamento + Windows + CI) |

## 8. Limitações conhecidas
- O PostgreSQL usa uma camada de tradução do SQL existente (não um ORM): consultas novas devem seguir o mesmo padrão.
- Conexão nova a cada operação (sem pool): suficiente para dezenas de usuários; pool (psycopg_pool) se necessário.
- Neste ambiente de testes, a imagem foi construída sem o cliente PostgreSQL (rede bloqueia o repositório Debian);
  o CI do GitHub constrói com ele. Backup via `pg_dump` foi testado fora do container.
- O S3 local do docker-compose (moto) guarda em memória: serve só para testes.
- Sessões ficam no banco (sem renovação automática): após `BIMOFFICE_SESSION_HOURS` é preciso entrar de novo.
