-- worker separado: sinal de vida e identificação de quem está executando a tarefa
ALTER TABLE jobs ADD COLUMN heartbeat_at TEXT;
ALTER TABLE jobs ADD COLUMN worker_id TEXT;
