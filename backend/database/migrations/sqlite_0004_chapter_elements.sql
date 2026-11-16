-- v0.7: GlobalIds dos elementos do IFC usados por cada capítulo (rastreabilidade memorial <-> modelo 3D)
ALTER TABLE memorial_chapters ADD COLUMN element_ids TEXT NOT NULL DEFAULT '[]';
