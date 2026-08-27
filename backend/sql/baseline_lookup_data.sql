--
-- PostgreSQL database dump
--


-- Dumped from database version 16.15 (Debian 16.15-1.pgdg13+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg13+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: tenant; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: app_user; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: cycle_config; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: document_template; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: event_category; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.event_category (id, code, description) VALUES (1, 'camp', 'Camp');
INSERT INTO public.event_category (id, code, description) VALUES (2, 'group_session', 'Group session');
INSERT INTO public.event_category (id, code, description) VALUES (3, 'leader_event', 'Leader event');
INSERT INTO public.event_category (id, code, description) VALUES (4, 'other', 'Other');


--
-- Data for Name: group_entity; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: event; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: finance_account; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: template; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: protocol; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: finance_transaction; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: participant; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: attendance_fine; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: audit_log; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: document_template_part; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: element_type; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.element_type (id, code, description) VALUES (1, 'text', 'Editable text');
INSERT INTO public.element_type (id, code, description) VALUES (2, 'todo', 'Todo element');
INSERT INTO public.element_type (id, code, description) VALUES (3, 'image', 'Image element');
INSERT INTO public.element_type (id, code, description) VALUES (4, 'display', 'Read-only display element');
INSERT INTO public.element_type (id, code, description) VALUES (5, 'static_text', 'Static text element');
INSERT INTO public.element_type (id, code, description) VALUES (6, 'form', 'Structured form block');
INSERT INTO public.element_type (id, code, description) VALUES (7, 'event_list', 'Filtered event list');
INSERT INTO public.element_type (id, code, description) VALUES (8, 'bullet_list', 'Bullet point list');
INSERT INTO public.element_type (id, code, description) VALUES (9, 'attendance', 'Attendance control block');
INSERT INTO public.element_type (id, code, description) VALUES (10, 'session_date', 'Next session date block');
INSERT INTO public.element_type (id, code, description) VALUES (11, 'matrix', 'Responsive matrix block');
INSERT INTO public.element_type (id, code, description) VALUES (12, 'entry_exit', 'Participant entry/exit block');


--
-- Data for Name: render_type; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.render_type (id, code, description) VALUES (1, 'heading', 'Heading block');
INSERT INTO public.render_type (id, code, description) VALUES (2, 'paragraph', 'Paragraph block');
INSERT INTO public.render_type (id, code, description) VALUES (3, 'todo_list', 'Todo list');
INSERT INTO public.render_type (id, code, description) VALUES (4, 'image', 'Image block');
INSERT INTO public.render_type (id, code, description) VALUES (5, 'key_value', 'Key-value output');
INSERT INTO public.render_type (id, code, description) VALUES (6, 'plain_text', 'Plain rendered text');
INSERT INTO public.render_type (id, code, description) VALUES (7, 'raw_latex', 'Raw LaTeX fragment');


--
-- Data for Name: element_definition; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: event_cycle; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: leader; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: list_definition; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: list_entry; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: platform_admin; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: platform_oidc_config; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: template_element; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: protocol_element; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: template_element_block; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: protocol_element_block; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: protocol_display_snapshot; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: stored_file; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: protocol_export_cache; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: protocol_image; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: protocol_text; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: submission_assignment; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: todo_status; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.todo_status (id, code, description) VALUES (1, 'open', 'Open');
INSERT INTO public.todo_status (id, code, description) VALUES (2, 'in_progress', 'In progress');
INSERT INTO public.todo_status (id, code, description) VALUES (3, 'done', 'Done');
INSERT INTO public.todo_status (id, code, description) VALUES (4, 'cancelled', 'Cancelled');


--
-- Data for Name: protocol_todo; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: role; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.role (id, code, description) VALUES (1, 'admin', 'Tenant administrator');
INSERT INTO public.role (id, code, description) VALUES (2, 'writer', 'Workspace write access');
INSERT INTO public.role (id, code, description) VALUES (3, 'reader', 'Read-only workspace access with PDF export');
INSERT INTO public.role (id, code, description) VALUES (4, 'kassier', 'Reader access plus full finance and fines management');


--
-- Data for Name: submission_upload; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: submission_upload_file; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: submission_upload_log; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: system_error_log; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: template_participant; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: tenant_domain; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: user_mfa_factor; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: user_protocol_access; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: user_protocol_scroll; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: user_role; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: user_template_access; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: user_tenant_role; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: word_import_document; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: word_import_profile; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: word_import_suggestion_outcome; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Name: app_user_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.app_user_id_seq', 1, false);


--
-- Name: attendance_fine_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.attendance_fine_id_seq', 1, false);


--
-- Name: audit_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.audit_log_id_seq', 1, false);


--
-- Name: cycle_config_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.cycle_config_id_seq', 1, false);


--
-- Name: document_template_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.document_template_id_seq', 1, false);


--
-- Name: document_template_part_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.document_template_part_id_seq', 1, false);


--
-- Name: element_definition_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.element_definition_id_seq', 1, false);


--
-- Name: element_type_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.element_type_id_seq', 12, true);


--
-- Name: event_category_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.event_category_id_seq', 4, true);


--
-- Name: event_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.event_id_seq', 1, false);


--
-- Name: finance_account_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.finance_account_id_seq', 1, false);


--
-- Name: finance_transaction_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.finance_transaction_id_seq', 1, false);


--
-- Name: group_entity_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.group_entity_id_seq', 1, false);


--
-- Name: leader_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.leader_id_seq', 1, false);


--
-- Name: list_definition_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.list_definition_id_seq', 1, false);


--
-- Name: list_entry_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.list_entry_id_seq', 1, false);


--
-- Name: participant_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.participant_id_seq', 1, false);


--
-- Name: platform_admin_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.platform_admin_id_seq', 1, false);


--
-- Name: platform_oidc_config_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.platform_oidc_config_id_seq', 1, false);


--
-- Name: protocol_display_snapshot_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.protocol_display_snapshot_id_seq', 1, false);


--
-- Name: protocol_element_block_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.protocol_element_block_id_seq', 1, false);


--
-- Name: protocol_element_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.protocol_element_id_seq', 1, false);


--
-- Name: protocol_export_cache_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.protocol_export_cache_id_seq', 1, false);


--
-- Name: protocol_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.protocol_id_seq', 1, false);


--
-- Name: protocol_image_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.protocol_image_id_seq', 1, false);


--
-- Name: protocol_text_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.protocol_text_id_seq', 1, false);


--
-- Name: protocol_todo_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.protocol_todo_id_seq', 1, false);


--
-- Name: render_type_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.render_type_id_seq', 7, true);


--
-- Name: role_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.role_id_seq', 4, true);


--
-- Name: stored_file_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.stored_file_id_seq', 1, false);


--
-- Name: submission_assignment_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.submission_assignment_id_seq', 1, false);


--
-- Name: submission_upload_file_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.submission_upload_file_id_seq', 1, false);


--
-- Name: submission_upload_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.submission_upload_id_seq', 1, false);


--
-- Name: submission_upload_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.submission_upload_log_id_seq', 1, false);


--
-- Name: system_error_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.system_error_log_id_seq', 1, false);


--
-- Name: template_element_block_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.template_element_block_id_seq', 1, false);


--
-- Name: template_element_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.template_element_id_seq', 1, false);


--
-- Name: template_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.template_id_seq', 1, false);


--
-- Name: tenant_domain_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.tenant_domain_id_seq', 1, false);


--
-- Name: tenant_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.tenant_id_seq', 1, false);


--
-- Name: todo_status_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.todo_status_id_seq', 4, true);


--
-- Name: user_mfa_factor_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.user_mfa_factor_id_seq', 1, false);


--
-- Name: word_import_document_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.word_import_document_id_seq', 1, false);


--
-- Name: word_import_profile_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.word_import_profile_id_seq', 1, false);


--
-- Name: word_import_suggestion_outcome_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.word_import_suggestion_outcome_id_seq', 1, false);


--
-- PostgreSQL database dump complete
--

SELECT setval(pg_get_serial_sequence('public.role', 'id'), (SELECT COALESCE(MAX(id), 1) FROM public.role), EXISTS (SELECT 1 FROM public.role));
SELECT setval(pg_get_serial_sequence('public.todo_status', 'id'), (SELECT COALESCE(MAX(id), 1) FROM public.todo_status), EXISTS (SELECT 1 FROM public.todo_status));
SELECT setval(pg_get_serial_sequence('public.element_type', 'id'), (SELECT COALESCE(MAX(id), 1) FROM public.element_type), EXISTS (SELECT 1 FROM public.element_type));
SELECT setval(pg_get_serial_sequence('public.render_type', 'id'), (SELECT COALESCE(MAX(id), 1) FROM public.render_type), EXISTS (SELECT 1 FROM public.render_type));
SELECT setval(pg_get_serial_sequence('public.event_category', 'id'), (SELECT COALESCE(MAX(id), 1) FROM public.event_category), EXISTS (SELECT 1 FROM public.event_category));
