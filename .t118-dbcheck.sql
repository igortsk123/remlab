select to_regclass('mesh_audit_marks') as marks, to_regclass('mesh_audit_notes') as notes,
  (select count(*) from information_schema.columns where table_name = 'mesh_audit_items'
     and column_name in ('mark', 'note', 'note_seq', 'poster_hd_url', 'mark_by', 'mark_at')) as new_cols,
  (select count(*) from pg_constraint where conname like 'mesh_audit_%_chk' or conname like 'mesh_audit_%_uq' or conname like 'mesh_audit_%_len') as named;
