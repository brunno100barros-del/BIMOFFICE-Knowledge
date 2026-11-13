# Publicação e arquitetura online — BIMOFFICE Knowledge

## 1. Como as peças se separam

```
 Navegador
   │
   ├── Interface (HTML/CSS/JS, pasta frontend/)
   │      • no seu PC: servida pelo próprio backend em http://127.0.0.1:8000/
   │      • na internet: GitHub Pages  →  https://brunno100barros-del.github.io/BIMOFFICE-Knowledge/
   │
   └── chama a API REST  ──►  Backend FastAPI (Python)
                                 • lê DOCX/PDF, cria trechos, gera vetores (modelo E5 local)
                                 • banco SQLite + FTS5, arquivos originais em data/
                                 • roda no seu PC hoje; num servidor do SENAI no futuro
```

O **GitHub Pages só hospeda a interface** (arquivos estáticos). Ele **não** executa Python,
FastAPI, SQLite, leitura de DOCX/PDF, o modelo de IA nem guarda documentos. Por isso:

| Onde a interface está aberta | Backend | O que funciona |
|---|---|---|
| `http://127.0.0.1:8000/` (iniciar.bat) | o seu PC | **tudo** |
| GitHub Pages, sem configurar | nenhum | **modo demonstração**: telas, tema, navegação. Avisa o que depende do backend. Nenhum dado é simulado. |
| GitHub Pages + Configurações → `http://127.0.0.1:8000` | o seu PC (iniciar.bat ligado) | **tudo**, mas só no computador onde o backend está ligado |
| GitHub Pages + endereço de um servidor | servidor (Etapa 6) | **tudo**, de qualquer lugar, com senha |

Os documentos institucionais **nunca** vão para o GitHub: ficam na pasta `data/` do backend
(`.gitignore`). A interface publicada não contém dados nem senhas.

## 2. Publicar no GitHub Pages (uma vez só)

1. No GitHub, abra o repositório → **Settings** → **Pages**.
2. Em **Build and deployment → Source**, escolha **GitHub Actions**.
3. Pronto. A cada atualização da `main`, o arquivo `.github/workflows/pages.yml`:
   1. roda os testes automáticos (se falharem, **não publica**);
   2. confere que a pasta `frontend/` não contém segredos;
   3. publica a pasta `frontend/`.
4. Acompanhe em **Actions**. O endereço final aparece no resumo da execução:
   `https://brunno100barros-del.github.io/BIMOFFICE-Knowledge/`

Observação: em contas gratuitas, o GitHub Pages só funciona com repositório **público**.
Tornar o repositório público expõe o **código** (não os documentos, que nunca vão ao Git).

Para publicar manualmente sem alterar código: **Actions → Testes e publicação no GitHub Pages → Run workflow**.

### Usar a página publicada com o backend do seu PC
1. Ligue o backend com `iniciar.bat`.
2. Abra a página do GitHub Pages → **Configurações** → endereço `http://127.0.0.1:8000` → **Salvar e testar**.
3. O endereço do GitHub Pages já está autorizado no backend (CORS). Se o navegador pedir
   permissão para "acessar dispositivos da rede local", permita.

## 3. Backend online (Etapa 6 — ainda não implantado)

Nada foi publicado na internet ainda. Para isso é preciso **decidir onde hospedar**:

- **Servidor interno do SENAI** (recomendado para dados institucionais): uma máquina Windows ou
  Linux com Python 3.13, acessível pela rede/VPN, com HTTPS fornecido pela TI.
- **Nuvem** (ex.: VPS Linux): exige atenção à LGPD e a política da instituição sobre documentos.

Requisitos mínimos do servidor: 4 GB de RAM (modelo E5 ≈ 1 GB), 5 GB de disco + documentos,
disco **persistente** (o banco SQLite e os originais ficam em `BIMOFFICE_DATA_DIR`).
Serviços "gratuitos" que apagam o disco ao reiniciar **não servem**.

### Variáveis de ambiente do backend

| Variável | Para quê | Exemplo |
|---|---|---|
| `BIMOFFICE_DATA_DIR` | pasta persistente de dados | `/srv/bimoffice/data` |
| `BIMOFFICE_API_TOKEN` | **senha da API** (obrigatória na internet) | uma senha longa e aleatória |
| `BIMOFFICE_CORS_ORIGINS` | sites que podem chamar a API | `https://brunno100barros-del.github.io` |
| `BIMOFFICE_EMBEDDING_MODEL` | trocar o modelo (opcional) | `intfloat/multilingual-e5-base` |

Comando: `uvicorn backend.main:app --host 0.0.0.0 --port 8000` atrás de um proxy HTTPS.
Com `BIMOFFICE_API_TOKEN` definido, toda chamada `/api/*` exige `Authorization: Bearer <senha>`
(exceto `/api/health` e `/api/config`). A senha é digitada em **Configurações** e fica só no
navegador do usuário — nunca no código nem no GitHub.

Limitações atuais da autenticação: é **uma senha compartilhada** (não há usuários individuais
nem perfis). Contas por usuário (ex.: login institucional) ficam para a Etapa 7.

## 4. Google Drive (Etapa 5 — ainda não implementado)

Depende de credenciais que só o dono da conta pode criar:
1. Projeto no **Google Cloud Console** → ativar **Google Drive API**.
2. **Tela de consentimento OAuth** (tipo Interno, se a conta for do Google Workspace do SENAI).
3. Credencial **ID do cliente OAuth** (aplicativo da Web) com o endereço de retorno do backend.
4. O ID e o segredo vão **somente** para variáveis de ambiente do backend.

Permissão planejada: `drive.readonly` (somente leitura), limitada à pasta escolhida pelo
usuário dentro do sistema. Fluxo: conectar → escolher pasta → listar DOCX/PDF/Google Docs →
importar manualmente → sincronizar manualmente (novos/modificados pelo `modifiedTime`/`md5Checksum`
do Drive, sem duplicar). A origem (pasta e arquivo) já tem lugar reservado no banco
(`documents.source = 'gdrive'` e `documents.source_ref`).
