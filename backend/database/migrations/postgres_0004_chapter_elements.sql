-- v0.7: GlobalIds dos elementos do IFC usados por cada capítulo (rastreabilidade memorial <-> modelo 3D)
ALTER TABLE memorial_chapters ADD COLUMN IF NOT EXISTS element_ids TEXT NOT NULL DEFAULT '[]';
