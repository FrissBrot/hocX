-- Messabfragen für Lasttests (psql gegen die DB des Lasttest-Stacks, als Superuser/Owner).
-- Jede Abfrage ist lesend. Abschnitte mit "\echo" trennen.

\echo '== Verbindungen je Rolle/Zustand (Pool-Auslastung aller Dienste) =='
SELECT usename, application_name, state, count(*) AS n,
       max(now() - state_change) FILTER (WHERE state = 'idle in transaction') AS longest_idle_in_tx
FROM pg_stat_activity WHERE datname = current_database()
GROUP BY 1, 2, 3 ORDER BY n DESC;

\echo '== Wer wartet auf wen (Lock-Wartezeiten) =='
SELECT waiting.pid AS waiting_pid, now() - waiting.query_start AS waiting_for,
       left(waiting.query, 120) AS waiting_query,
       blocking.pid AS blocking_pid, blocking.state AS blocking_state,
       left(blocking.query, 120) AS blocking_query
FROM pg_stat_activity waiting
JOIN LATERAL unnest(pg_blocking_pids(waiting.pid)) AS b(pid) ON true
JOIN pg_stat_activity blocking ON blocking.pid = b.pid
ORDER BY waiting_for DESC;

\echo '== Gehaltene Advisory Locks (Hintergrundjobs: 2026000xx, Upload-Lock ns 909100001) =='
SELECT l.pid, l.classid, l.objid, l.mode, l.granted, a.state, now() - a.xact_start AS xact_age, left(a.query, 80) AS query
FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.locktype = 'advisory' ORDER BY l.granted, xact_age DESC;

\echo '== storage_state-Sperren (FOR SHARE aller Schreiber, UPDATE durch Backup/Cutover) =='
SELECT l.pid, l.mode, l.granted, now() - a.xact_start AS xact_age, left(a.query, 80) AS query
FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.relation = 'storage_state'::regclass;

\echo '== Teuerste Abfragen (pg_stat_statements; vorher SELECT pg_stat_statements_reset();) =='
SELECT calls, round(total_exec_time::numeric, 0) AS total_ms, round(mean_exec_time::numeric, 1) AS mean_ms,
       round(max_exec_time::numeric, 0) AS max_ms, rows, left(regexp_replace(query, '\s+', ' ', 'g'), 140) AS query
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 25;

\echo '== Temp-Dateien / Sortierungen über work_mem =='
SELECT temp_files, pg_size_pretty(temp_bytes) AS temp_bytes, deadlocks, conflicts
FROM pg_stat_database WHERE datname = current_database();

\echo '== Warteschlangen der Hintergrundverarbeitung =='
SELECT 'gallery_upload_job' AS queue, status, count(*), min(created_at) AS oldest FROM gallery_upload_job GROUP BY status
UNION ALL SELECT 'photo_analysis_job', status, count(*), min(created_at) FROM photo_analysis_job GROUP BY status
UNION ALL SELECT 'tenant_data_export', status, count(*), min(created_at) FROM tenant_data_export GROUP BY status
ORDER BY 1, 2;

\echo '== Dauer der letzten Hintergrundläufe =='
SELECT job_name, status, started_at, finished_at - started_at AS duration
FROM system_job_run ORDER BY started_at DESC LIMIT 30;
