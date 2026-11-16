-- worker separado: sinal de vida e identificação de quem está executando a tarefa
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS heartbeat_at TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS worker_id TEXT;
