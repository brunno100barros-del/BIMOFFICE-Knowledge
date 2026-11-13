/*
 * Configuração da interface BIMOFFICE Knowledge.
 *
 * apiBase: endereço do backend FastAPI.
 *   null  -> automático: se a página foi aberta pelo próprio backend
 *            (http://127.0.0.1:8000), usa o mesmo endereço; no GitHub Pages,
 *            fica sem backend até você informar um em Configurações.
 *   "https://meu-backend.exemplo.br" -> backend hospedado na internet (Etapa 6).
 *
 * NUNCA coloque senhas, tokens ou credenciais neste arquivo: ele é público.
 */
window.BIMOFFICE_CONFIG = {
  apiBase: null,
};
