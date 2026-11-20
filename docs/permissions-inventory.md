# Berechtigungs-Inventar

GENERIERT von `python3 scripts/sync-route-permissions.py` (Plan «Berechtigungen, Datei-Kontexte
und Kontext-Freigaben», Phase 0). Nicht von Hand bearbeiten. Quelle: `permissions/route-map.json`;
Rollen-Matrix: `permissions/permission-matrix.json` (geprüft von `tests/test_permission_matrix.py`).

## Übersicht

- Routen gesamt: 583 (Plattform-Admin: 127)
- Mandanten-Routen mit Rechteprüfung: 378
- Mandanten-Routen mit eigenem Sicherheitsmodell (begründete Ausnahme): 78
- Mandanten-Routen ohne Prüfung und ohne Begründung (Lücken): 0
- Routen, die Dateiinhalt ausliefern: 22

## Lücken (Routen ohne Prüfung und ohne Begründung)

Keine – `tests/test_route_permission_inventory.py` verhindert neue.

## Befunde Phase 0 (18.11.2026)

- Die statische Analyse rechnete Methodenaufrufe (`service.repository.list_assignments(...)`)
  der gleichnamigen Route zu und zeigte dadurch mehr Prüfungen als tatsächlich laufen. Behoben;
  betroffen waren zehn Routen, inhaltlich nur `GET /api/submission-assignments/summaries`
  (angezeigt `submissions.manage`, geprüft `submissions.read` – Leser sehen den Fortschritt aller
  Abgaben; passt zu ihrem Leserecht, keine Lücke). Bei den übrigen fiel nur `meetings.read` weg,
  das `meetings.edit`/`templates.edit`/`files.manage` ohnehin enthalten bzw. voraussetzen.
- Laufzeit-Matrix (`tests/test_permission_matrix.py`): alle GET-Routen weisen genau die Rollen
  ausserhalb der Matrix mit 403 ab.

## Dateiauslieferung (Download, Vorschau, Thumbnail, ZIP, Export)

| Route | Handler | Prüfung |
|---|---|---|
| `GET /api/admin/storage/migrations/{migration_id}/report` | admin_storage.download_report | Plattform-Admin |
| `POST /api/admin/tenants/{tenant_id}/export` | admin.export_tenant | Plattform-Admin |
| `GET /api/document-assets/{asset_id}/content` | document_studio.get_document_asset_content | meetings.read |
| `GET /api/document-studio/examples/{example_key}/thumbnail` | document_studio.get_design_example_thumbnail | meetings.read |
| `GET /api/document-studio/fonts/{file_name}` | document_studio.get_builtin_font | meetings.read |
| `GET /api/document-templates/{template_id}/thumbnail` | document_studio.get_document_template_thumbnail | meetings.read |
| `POST /api/documents/export` | documents.export_document_format | meetings.read |
| `GET /api/documents/{document_id}/versions/{version_id}/files/{role}` | managed_documents.get_document_file | meetings.read |
| `GET /api/files/trash/{file_id}/thumbnail` | files.get_trash_thumbnail | files.manage oder photos.manage |
| `GET /api/public/calendar/{token}.ics` | calendar_feeds.get_calendar_feed | öffentlicher .ics-Abruf: Token + can_subscribe in calendar_feed_service.resolve |
| `GET /api/public/share/{token}/download` | public_share.download_public_share_all | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `GET /api/public/share/{token}/files/{file_id}/download` | public_share.download_public_share_file | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `GET /api/public/share/{token}/files/{file_id}/thumbnail` | public_share.get_public_share_thumbnail | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `GET /api/public/share/{token}/files/{file_id}/view` | public_share.view_public_share_file | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `POST /api/public/submission-access/download` | public_submission_access.download_submission_file | persönlicher Abgabe-Link: Token im Body + Rate-Limit (submission_access_service) |
| `GET /api/stored-files/{stored_file_id}/content` | files.get_stored_file_content | meetings.read |
| `GET /api/stored-files/{stored_file_id}/download` | files.download_stored_file | meetings.read |
| `GET /api/stored-files/{stored_file_id}/thumbnail` | files.get_stored_file_thumbnail | meetings.read |
| `GET /api/submission-assignments/{assignment_id}/download-zip` | submission_assignments.download_all_files_zip | submissions.read |
| `GET /api/submission-uploads/{upload_id}/files/{file_id}/content` | submission_assignments.get_submission_file_content | submissions.read |
| `GET /api/submission-uploads/{upload_id}/files/{file_id}/thumbnail` | submission_assignments.get_submission_file_thumbnail | submissions.read |
| `GET /api/tenant-data-exports/{export_id}/download` | tenant_data_export.download_tenant_data_export | data.export |

## Eigenes Sicherheitsmodell (begründete Ausnahmen)

| Route | Begründung |
|---|---|
| `POST /api/admin/auth/login` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `POST /api/admin/auth/logout` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `POST /api/admin/auth/mfa/totp/setup/complete` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `POST /api/admin/auth/mfa/totp/setup/start` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `POST /api/admin/auth/mfa/totp/verify` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `GET /api/admin/auth/oidc/authorize` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `GET /api/admin/auth/oidc/callback` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `GET /api/admin/auth/oidc/public-config` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `GET /api/admin/auth/session` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `POST /api/auth/account-link/complete` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/account-link/preview` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `GET /api/auth/bridge` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/bridge` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/bridge/preview` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/login` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/logout` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/passkeys/assertion/start` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/passkeys/assertion/verify` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/passkeys/setup/complete` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/passkeys/setup/start` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/setup/skip` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/totp/setup/complete` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/totp/setup/start` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/totp/verify` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `GET /api/auth/password-reset/available` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/password-reset/request` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `GET /api/auth/session` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `GET /api/auth/tenant-by-domain` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `GET /api/calendar-feeds` | eigene Kalender-Abos |
| `DELETE /api/calendar-feeds/{kind}` | eigene Kalender-Abos |
| `GET /api/fines` | eigene Bussen; alle nur mit reports.personal (im Rumpf) |
| `GET /api/fines/open-summary` | Summe der eigenen Bussen; alle nur mit reports.personal (im Rumpf, wie list_fines) |
| `GET /api/public/calendar/{token}.ics` | öffentlicher .ics-Abruf: Token + can_subscribe in calendar_feed_service.resolve |
| `GET /api/public/customers` | öffentlicher Preis-/Kundenkatalog der Website |
| `GET /api/public/maintenance-status` | öffentlicher Wartungsstatus |
| `GET /api/public/plan-comparison` | öffentlicher Preis-/Kundenkatalog der Website |
| `GET /api/public/plans` | öffentlicher Preis-/Kundenkatalog der Website |
| `GET /api/public/share/{token}` | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `GET /api/public/share/{token}/download` | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `GET /api/public/share/{token}/files/{file_id}/download` | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `GET /api/public/share/{token}/files/{file_id}/thumbnail` | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `GET /api/public/share/{token}/files/{file_id}/view` | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `POST /api/public/submission-access/download` | persönlicher Abgabe-Link: Token im Body + Rate-Limit (submission_access_service) |
| `POST /api/public/submission-access/upload` | persönlicher Abgabe-Link: Token im Body + Rate-Limit (submission_access_service) |
| `POST /api/public/submission-access/view` | persönlicher Abgabe-Link: Token im Body + Rate-Limit (submission_access_service) |
| `POST /api/public/submission-access/withdraw` | persönlicher Abgabe-Link: Token im Body + Rate-Limit (submission_access_service) |
| `GET /api/system-status/summary` | Status-Token (kein Benutzer) |
| `GET /api/tenants` | TenantService._manageable_tenant_ids (settings.manage) |
| `PATCH /api/tenants/{tenant_id}` | TenantService (settings.manage) |
| `GET /api/tenants/{tenant_id}/charges` | TenantService (settings.manage) |
| `GET /api/tenants/{tenant_id}/domains` | TenantService (settings.manage) |
| `POST /api/tenants/{tenant_id}/domains` | TenantService.require_manageable (settings.manage) |
| `DELETE /api/tenants/{tenant_id}/domains/{domain_id}` | TenantService.require_manageable (settings.manage) |
| `POST /api/tenants/{tenant_id}/domains/{domain_id}/verify` | TenantService.require_manageable (settings.manage) |
| `GET /api/tenants/{tenant_id}/profile-image` | Vereinslogo (auch für die Login-Seite) |
| `GET /api/tenants/{tenant_id}/subscription` | TenantService (settings.manage) |
| `GET /api/todo-fines` | eigene Pendenzen-Bussen; alle nur mit reports.personal (im Rumpf) |
| `GET /api/users` | UserService (access.manage) |
| `POST /api/users` | UserService (access.manage) |
| `GET /api/users/me` | eigenes Konto |
| `PATCH /api/users/me` | eigenes Konto |
| `GET /api/users/me/mfa` | eigene MFA |
| `DELETE /api/users/me/mfa/factors/{factor_id}` | eigene MFA |
| `POST /api/users/me/mfa/passkeys/complete` | eigene MFA |
| `POST /api/users/me/mfa/passkeys/start` | eigene MFA |
| `PATCH /api/users/me/mfa/preferred-method` | eigene MFA |
| `POST /api/users/me/mfa/totp/complete` | eigene MFA |
| `POST /api/users/me/mfa/totp/start` | eigene MFA |
| `GET /api/users/me/notification-preferences` | eigene E-Mail-Benachrichtigungen |
| `PUT /api/users/me/notification-preferences` | eigene E-Mail-Benachrichtigungen |
| `POST /api/users/me/password` | eigenes Passwort |
| `POST /api/users/me/personal-data` | eigene Datenauskunft (rate-limitiert) |
| `DELETE /api/users/{user_id}` | UserService (access.manage) |
| `GET /api/users/{user_id}` | UserService (access.manage) |
| `PATCH /api/users/{user_id}` | UserService (access.manage) |
| `GET /api/users/{user_id}/mfa` | MfaService._managed_user (access.manage) |
| `DELETE /api/users/{user_id}/mfa/factors/{factor_id}` | MfaService._managed_user (access.manage) |
| `WEBSOCKET /api/ws/protocols/{protocol_id}` | WebSocket: can_read_protocol beim Verbinden und alle 30 s, Schreiben nur mit meetings.edit (_can_edit) |

## Alle Mandanten-Routen

| Route | Prüfung |
|---|---|
| `GET /api/activity` | activity.read |
| `POST /api/admin/auth/login` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `POST /api/admin/auth/logout` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `POST /api/admin/auth/mfa/totp/setup/complete` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `POST /api/admin/auth/mfa/totp/setup/start` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `POST /api/admin/auth/mfa/totp/verify` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `GET /api/admin/auth/oidc/authorize` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `GET /api/admin/auth/oidc/callback` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `GET /api/admin/auth/oidc/public-config` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `GET /api/admin/auth/session` | Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit) |
| `GET /api/agenda-items` | meetings.read |
| `POST /api/agenda-items` | meetings.edit |
| `GET /api/agenda-items/template-preference` | meetings.edit |
| `PUT /api/agenda-items/template-preference` | meetings.edit |
| `GET /api/agenda-items/templates` | meetings.read |
| `DELETE /api/agenda-items/{item_id}` | meetings.edit |
| `PATCH /api/agenda-items/{item_id}` | meetings.edit |
| `POST /api/agenda-items/{item_id}/postpone` | meetings.edit |
| `POST /api/auth/account-link/complete` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/account-link/preview` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `GET /api/auth/bridge` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/bridge` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/bridge/preview` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/login` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/logout` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/passkeys/assertion/start` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/passkeys/assertion/verify` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/passkeys/setup/complete` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/passkeys/setup/start` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/setup/skip` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/totp/setup/complete` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/totp/setup/start` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/mfa/totp/verify` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `GET /api/auth/password-reset/available` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `POST /api/auth/password-reset/request` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `GET /api/auth/session` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `GET /api/auth/tenant-by-domain` | Anmeldung, MFA beim Login, Session, Domain-Bridge, Passwort vergessen, Einladung |
| `GET /api/calendar-feeds` | eigene Kalender-Abos |
| `DELETE /api/calendar-feeds/{kind}` | eigene Kalender-Abos |
| `PUT /api/calendar-feeds/{kind}` | meetings.read |
| `POST /api/calendar-feeds/{kind}/regenerate` | meetings.read |
| `GET /api/clamav/status` | submissions.read |
| `GET /api/context-files/submission-photos` | meetings.read |
| `GET /api/context-visibility` | settings.manage |
| `PUT /api/context-visibility/{module}` | settings.manage |
| `GET /api/cycle-configs` | meetings.read |
| `POST /api/cycle-configs` | templates.manage |
| `DELETE /api/cycle-configs/{cycle_config_id}` | templates.manage |
| `GET /api/cycle-configs/{cycle_config_id}` | meetings.read |
| `PUT /api/cycle-configs/{cycle_config_id}` | templates.manage |
| `GET /api/cycle-configs/{cycle_config_id}/cycles` | meetings.read |
| `GET /api/document-assets` | meetings.read |
| `POST /api/document-assets` | settings.manage |
| `POST /api/document-assets/merge-duplicates` | settings.manage |
| `DELETE /api/document-assets/{asset_id}` | settings.manage |
| `PATCH /api/document-assets/{asset_id}` | settings.manage |
| `GET /api/document-assets/{asset_id}/content` | meetings.read |
| `GET /api/document-assets/{asset_id}/references` | meetings.read |
| `GET /api/document-brands` | meetings.read |
| `POST /api/document-brands` | settings.manage |
| `DELETE /api/document-brands/{brand_id}` | settings.manage |
| `GET /api/document-brands/{brand_id}` | meetings.read |
| `PATCH /api/document-brands/{brand_id}` | settings.manage |
| `POST /api/document-brands/{brand_id}/archive` | settings.manage |
| `GET /api/document-brands/{brand_id}/revisions` | meetings.read |
| `POST /api/document-brands/{brand_id}/revisions/{revision_id}/restore` | settings.manage |
| `GET /api/document-components` | meetings.read |
| `POST /api/document-components` | templates.edit · Feature document_designer |
| `DELETE /api/document-components/{component_id}` | templates.edit |
| `PATCH /api/document-components/{component_id}` | templates.edit · Feature document_designer |
| `GET /api/document-settings` | meetings.read |
| `PATCH /api/document-settings` | settings.manage |
| `GET /api/document-studio/capabilities` | meetings.read |
| `GET /api/document-studio/catalog` | meetings.read |
| `GET /api/document-studio/examples` | meetings.read |
| `POST /api/document-studio/examples/{example_key}/import` | settings.manage, templates.edit · Feature document_designer |
| `GET /api/document-studio/examples/{example_key}/thumbnail` | meetings.read |
| `GET /api/document-studio/fonts/{file_name}` | meetings.read |
| `GET /api/document-studio/session-templates/{template_id}/designs` | meetings.read |
| `POST /api/document-studio/session-templates/{template_id}/designs/{document_type}` | templates.edit · Feature document_designer |
| `GET /api/document-template-assignments` | meetings.read |
| `PUT /api/document-template-assignments` | settings.manage |
| `GET /api/document-templates` | meetings.read |
| `POST /api/document-templates` | templates.edit · Feature document_designer |
| `POST /api/document-templates/archive-unused` | settings.manage, templates.edit |
| `POST /api/document-templates/validate` | meetings.read |
| `DELETE /api/document-templates/{template_id}` | settings.manage, templates.edit |
| `GET /api/document-templates/{template_id}` | meetings.read |
| `PATCH /api/document-templates/{template_id}` | settings.manage, templates.edit · Feature document_designer |
| `POST /api/document-templates/{template_id}/archive` | settings.manage, templates.edit |
| `GET /api/document-templates/{template_id}/compare` | meetings.read |
| `DELETE /api/document-templates/{template_id}/draft` | templates.edit |
| `PUT /api/document-templates/{template_id}/draft` | templates.edit · Feature document_designer |
| `POST /api/document-templates/{template_id}/duplicate` | templates.edit · Feature document_designer |
| `GET /api/document-templates/{template_id}/protocol-structure` | meetings.read |
| `POST /api/document-templates/{template_id}/publish` | settings.manage, templates.edit · Feature document_designer |
| `GET /api/document-templates/{template_id}/revisions` | meetings.read |
| `GET /api/document-templates/{template_id}/revisions/{revision_id}` | meetings.read |
| `POST /api/document-templates/{template_id}/revisions/{revision_id}/restore` | templates.edit · Feature document_designer |
| `GET /api/document-templates/{template_id}/thumbnail` | meetings.read |
| `GET /api/document-verification` | meetings.read |
| `PATCH /api/document-verification` | settings.manage |
| `DELETE /api/document-verification/request` | settings.manage |
| `POST /api/document-verification/request` | settings.manage |
| `POST /api/documents/export` | meetings.read |
| `POST /api/documents/export/columns` | meetings.read |
| `POST /api/documents/export/preview` | meetings.read |
| `GET /api/documents/exports` | meetings.read |
| `POST /api/documents/preview` | meetings.read, settings.manage, templates.edit |
| `POST /api/documents/preview/canvas` | meetings.read, settings.manage, templates.edit |
| `POST /api/documents/render` | meetings.read |
| `GET /api/documents/render-jobs/{job_id}` | meetings.read |
| `GET /api/documents/sources/{source}` | finances.read, meetings.read + meetings.edit oder participants.manage + meetings.read_drafts oder photos.read · je nach Fall: meetings.edit |
| `GET /api/documents/{document_id}` | meetings.read |
| `POST /api/documents/{document_id}/reprocess` | meetings.edit |
| `GET /api/documents/{document_id}/versions/{version_id}/files/{role}` | meetings.read |
| `GET /api/documents/{document_id}/versions/{version_id}/text` | meetings.read |
| `GET /api/element-definitions` | meetings.read |
| `POST /api/element-definitions` | templates.edit |
| `DELETE /api/element-definitions/{element_definition_id}` | templates.edit |
| `GET /api/element-definitions/{element_definition_id}` | meetings.read |
| `PATCH /api/element-definitions/{element_definition_id}` | templates.edit |
| `GET /api/event-field-config` | meetings.read |
| `PUT /api/event-field-config` | settings.manage |
| `GET /api/events` | meetings.read |
| `POST /api/events` | meetings.edit |
| `POST /api/events/import-csv` | meetings.edit |
| `POST /api/events/import-csv/preview` | meetings.edit |
| `POST /api/events/rename-tag` | meetings.edit |
| `DELETE /api/events/{event_id}` | meetings.edit |
| `PATCH /api/events/{event_id}` | meetings.edit |
| `GET /api/events/{event_id}/delete-impact` | meetings.edit |
| `GET /api/files` | files.read oder photos.read · je nach Fall: photos.read |
| `GET /api/files/album-pending-releases` | photos.read |
| `GET /api/files/album-share-requests` | photos.read |
| `GET /api/files/albums` | photos.read |
| `POST /api/files/albums` | photos.manage |
| `DELETE /api/files/albums/{album_id}` | photos.manage |
| `PATCH /api/files/albums/{album_id}` | photos.manage |
| `POST /api/files/albums/{album_id}/items` | photos.manage, photos.read |
| `POST /api/files/albums/{album_id}/items/remove` | photos.manage, photos.read |
| `PATCH /api/files/albums/{album_id}/items/{file_id}/best` | photos.manage, photos.read |
| `PATCH /api/files/albums/{album_id}/my-share` | photos.manage |
| `POST /api/files/albums/{album_id}/release` | photos.manage |
| `POST /api/files/albums/{album_id}/respond` | photos.manage · Feature photo_sharing |
| `POST /api/files/albums/{album_id}/shares` | photos.manage · Feature photo_sharing |
| `DELETE /api/files/albums/{album_id}/shares/{tenant_public_id}` | photos.manage |
| `PATCH /api/files/albums/{album_id}/shares/{tenant_public_id}` | photos.manage · Feature photo_sharing |
| `GET /api/files/analysis-progress` | photos.read |
| `POST /api/files/bulk-capture-date` | photos.manage |
| `POST /api/files/bulk-delete` | photos.manage |
| `POST /api/files/bulk-tags` | photos.manage · je nach Fall: files.manage |
| `POST /api/files/document-uploads` | files.manage · je nach Fall: submissions.manage |
| `GET /api/files/gallery-upload-jobs` | photos.manage |
| `GET /api/files/gallery-upload-jobs/{job_id}` | photos.manage |
| `POST /api/files/gallery-uploads` | photos.manage · je nach Fall: submissions.manage |
| `GET /api/files/similarity-groups` | photos.read |
| `GET /api/files/stats` | files.read oder photos.read |
| `GET /api/files/tags` | files.read oder photos.read |
| `GET /api/files/timeline` | photos.read |
| `GET /api/files/trash` | files.manage oder photos.manage |
| `POST /api/files/trash` | files.manage oder photos.manage |
| `POST /api/files/trash/empty` | files.manage oder photos.manage |
| `POST /api/files/trash/purge` | files.manage oder photos.manage |
| `POST /api/files/trash/restore` | files.manage oder photos.manage |
| `GET /api/files/trash/{file_id}/thumbnail` | files.manage oder photos.manage |
| `POST /api/files/upload-precheck` | files.manage oder photos.manage |
| `GET /api/files/upload-target-shared-albums` | photos.manage · je nach Fall: submissions.manage |
| `PATCH /api/files/{file_id}/best` | photos.manage |
| `GET /api/finance-settings` | meetings.read |
| `PATCH /api/finance-settings` | settings.manage |
| `GET /api/finance/accounts` | finances.read |
| `POST /api/finance/accounts` | finances.manage |
| `DELETE /api/finance/accounts/{account_id}` | finances.manage |
| `PATCH /api/finance/accounts/{account_id}` | finances.manage |
| `GET /api/finance/accounts/{account_id}/balance` | finances.read |
| `GET /api/finance/accounts/{account_id}/summary` | finances.read |
| `GET /api/finance/accounts/{account_id}/transactions` | finances.read |
| `POST /api/finance/accounts/{account_id}/transactions` | finances.manage |
| `DELETE /api/finance/transactions/{tx_id}` | finances.manage |
| `PATCH /api/finance/transactions/{tx_id}` | finances.manage |
| `GET /api/fines` | eigene Bussen; alle nur mit reports.personal (im Rumpf) · Feature finance (lesen) |
| `POST /api/fines` | fines.manage |
| `GET /api/fines/open-summary` | Summe der eigenen Bussen; alle nur mit reports.personal (im Rumpf, wie list_fines) · Feature finance (lesen) |
| `GET /api/fines/tariff` | meetings.read · Feature finance (lesen) |
| `PUT /api/fines/tariff` | fines.manage · Feature finance |
| `DELETE /api/fines/{fine_id}` | fines.manage |
| `POST /api/fines/{fine_id}/collect` | fines.manage |
| `POST /api/fines/{fine_id}/reopen` | fines.manage |
| `POST /api/fines/{fine_id}/restore` | fines.manage |
| `GET /api/list-entries` | meetings.edit |
| `DELETE /api/list-entries/{list_entry_id}` | meetings.edit |
| `PATCH /api/list-entries/{list_entry_id}` | meetings.edit |
| `GET /api/lists` | meetings.edit |
| `POST /api/lists` | meetings.edit |
| `DELETE /api/lists/{list_definition_id}` | meetings.edit |
| `PATCH /api/lists/{list_definition_id}` | meetings.edit |
| `POST /api/lists/{list_definition_id}/columns` | meetings.edit |
| `PUT /api/lists/{list_definition_id}/columns/order` | meetings.edit |
| `DELETE /api/lists/{list_definition_id}/columns/{column_id}` | meetings.edit |
| `PATCH /api/lists/{list_definition_id}/columns/{column_id}` | meetings.edit |
| `GET /api/lists/{list_definition_id}/columns/{column_id}/usages` | meetings.edit |
| `GET /api/lists/{list_definition_id}/entries` | meetings.edit |
| `POST /api/lists/{list_definition_id}/entries` | meetings.edit |
| `DELETE /api/participants` | participants.manage · je nach Fall: access.manage |
| `GET /api/participants` | participants.read |
| `POST /api/participants` | participants.manage |
| `POST /api/participants/bulk-invite` | access.manage, participants.manage |
| `POST /api/participants/bulk-roles` | access.manage, participants.manage |
| `POST /api/participants/import-csv` | participants.manage |
| `GET /api/participants/invites` | access.manage |
| `DELETE /api/participants/{participant_id}` | participants.manage · je nach Fall: access.manage |
| `GET /api/participants/{participant_id}` | participants.read |
| `PATCH /api/participants/{participant_id}` | participants.manage · je nach Fall: access.manage |
| `DELETE /api/participants/{participant_id}/invite` | access.manage, participants.manage |
| `POST /api/participants/{participant_id}/invite` | access.manage, participants.manage |
| `POST /api/participants/{participant_id}/personal-data` | participants.export |
| `GET /api/participants/{participant_id}/templates` | meetings.read |
| `PUT /api/participants/{participant_id}/templates` | participants.manage |
| `GET /api/privacy-settings` | settings.manage |
| `PATCH /api/privacy-settings` | settings.manage |
| `DELETE /api/protocol-element-blocks/{protocol_element_block_id}` | meetings.edit |
| `PATCH /api/protocol-element-blocks/{protocol_element_block_id}` | meetings.edit |
| `POST /api/protocol-element-blocks/{protocol_element_block_id}/attendance/{participant_id}` | meetings.edit |
| `GET /api/protocol-element-blocks/{protocol_element_block_id}/images` | meetings.read |
| `POST /api/protocol-element-blocks/{protocol_element_block_id}/images` | meetings.edit |
| `POST /api/protocol-element-blocks/{protocol_element_block_id}/list-snapshot/entries/{entry_id}/accept-tracked-change` | meetings.edit |
| `POST /api/protocol-element-blocks/{protocol_element_block_id}/list-snapshot/refresh` | meetings.edit |
| `POST /api/protocol-element-blocks/{protocol_element_block_id}/list-snapshot/sync` | meetings.edit |
| `POST /api/protocol-element-blocks/{protocol_element_block_id}/list-snapshot/undo` | meetings.edit |
| `POST /api/protocol-element-blocks/{protocol_element_block_id}/rows/{row_id}/accept-tracked-change` | meetings.edit |
| `PUT /api/protocol-element-blocks/{protocol_element_block_id}/text` | meetings.edit |
| `POST /api/protocol-element-blocks/{protocol_element_block_id}/text/accept-tracked-changes` | meetings.edit |
| `GET /api/protocol-element-blocks/{protocol_element_block_id}/todos` | meetings.read |
| `POST /api/protocol-element-blocks/{protocol_element_block_id}/todos` | meetings.edit |
| `PATCH /api/protocol-elements/{protocol_element_id}` | meetings.edit |
| `POST /api/protocol-elements/{protocol_element_id}/blocks/from-event` | meetings.edit |
| `DELETE /api/protocol-images/{image_id}` | meetings.edit |
| `DELETE /api/protocol-todos/{todo_id}` | meetings.edit |
| `PATCH /api/protocol-todos/{todo_id}` | meetings.edit oder todos.complete_own |
| `POST /api/protocol-todos/{todo_id}/accept-tracked-change` | meetings.edit |
| `GET /api/protocol-todos/{todo_id}/details` | meetings.read |
| `PUT /api/protocol-todos/{todo_id}/details` | meetings.edit |
| `GET /api/protocol-todos/{todo_id}/due-events` | meetings.read |
| `GET /api/protocol-todos/{todo_id}/fine` | meetings.read · Feature todo_fines (lesen) |
| `PUT /api/protocol-todos/{todo_id}/fine` | fines.manage · Feature todo_fines |
| `POST /api/protocol-todos/{todo_id}/fine/preview` | fines.manage · Feature todo_fines |
| `GET /api/protocols` | meetings.read |
| `POST /api/protocols/from-template` | meetings.edit |
| `GET /api/protocols/next-session` | meetings.read |
| `GET /api/protocols/preview` | meetings.edit |
| `GET /api/protocols/template-preference` | meetings.edit |
| `PUT /api/protocols/template-preference` | meetings.edit |
| `GET /api/protocols/upcoming-sessions` | meetings.read |
| `DELETE /api/protocols/{protocol_id}` | meetings.edit |
| `GET /api/protocols/{protocol_id}` | meetings.read |
| `PATCH /api/protocols/{protocol_id}` | meetings.edit · je nach Fall: meetings.approve |
| `GET /api/protocols/{protocol_id}/agenda-items` | meetings.read |
| `POST /api/protocols/{protocol_id}/agenda-items` | meetings.edit |
| `POST /api/protocols/{protocol_id}/attendance/{participant_id}/excuse` | meetings.edit |
| `GET /api/protocols/{protocol_id}/block-images` | meetings.read |
| `GET /api/protocols/{protocol_id}/block-todos` | meetings.read |
| `GET /api/protocols/{protocol_id}/cycle-events` | meetings.read |
| `POST /api/protocols/{protocol_id}/delete` | meetings.edit |
| `GET /api/protocols/{protocol_id}/deletion-preview` | meetings.edit |
| `GET /api/protocols/{protocol_id}/elements` | meetings.read |
| `GET /api/protocols/{protocol_id}/fines` | reports.personal · Feature finance (lesen) |
| `GET /api/protocols/{protocol_id}/pdf-coverage` | meetings.read |
| `GET /api/protocols/{protocol_id}/pending-fines` | reports.personal · Feature finance (lesen) |
| `GET /api/protocols/{protocol_id}/pending-todos` | meetings.read |
| `GET /api/protocols/{protocol_id}/period` | meetings.read |
| `POST /api/protocols/{protocol_id}/quick-todos` | meetings.edit |
| `POST /api/protocols/{protocol_id}/revert-status` | meetings.edit · je nach Fall: meetings.approve |
| `GET /api/protocols/{protocol_id}/scroll-position` | meetings.read |
| `PUT /api/protocols/{protocol_id}/scroll-position` | meetings.read |
| `POST /api/protocols/{protocol_id}/sync-template` | meetings.edit |
| `GET /api/public-links` | settings.manage |
| `GET /api/public/calendar/{token}.ics` | öffentlicher .ics-Abruf: Token + can_subscribe in calendar_feed_service.resolve |
| `GET /api/public/customers` | öffentlicher Preis-/Kundenkatalog der Website |
| `GET /api/public/maintenance-status` | öffentlicher Wartungsstatus |
| `GET /api/public/plan-comparison` | öffentlicher Preis-/Kundenkatalog der Website |
| `GET /api/public/plans` | öffentlicher Preis-/Kundenkatalog der Website |
| `GET /api/public/share/{token}` | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `GET /api/public/share/{token}/download` | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `GET /api/public/share/{token}/files/{file_id}/download` | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `GET /api/public/share/{token}/files/{file_id}/thumbnail` | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `GET /api/public/share/{token}/files/{file_id}/view` | öffentliche Freigabelinks: Token + Rate-Limit (share_link_service) |
| `POST /api/public/submission-access/download` | persönlicher Abgabe-Link: Token im Body + Rate-Limit (submission_access_service) |
| `POST /api/public/submission-access/upload` | persönlicher Abgabe-Link: Token im Body + Rate-Limit (submission_access_service) |
| `POST /api/public/submission-access/view` | persönlicher Abgabe-Link: Token im Body + Rate-Limit (submission_access_service) |
| `POST /api/public/submission-access/withdraw` | persönlicher Abgabe-Link: Token im Body + Rate-Limit (submission_access_service) |
| `GET /api/retention/policy` | settings.manage |
| `PUT /api/retention/policy` | settings.manage |
| `GET /api/retention/proposals` | settings.manage |
| `POST /api/retention/proposals/decide` | settings.manage |
| `POST /api/retention/proposals/refresh` | settings.manage |
| `GET /api/roles` | access.manage |
| `POST /api/roles` | access.manage · Feature custom_roles |
| `GET /api/roles/catalog` | access.manage |
| `DELETE /api/roles/{role_id}` | access.manage |
| `PATCH /api/roles/{role_id}` | access.manage · Feature custom_roles |
| `POST /api/search` | files.read oder participants.read oder photos.read oder templates.edit |
| `GET /api/share-links` | sharing.public |
| `POST /api/share-links` | sharing.public + files.read oder photos.read · je nach Fall: files.read, photos.read · Feature photo_sharing |
| `DELETE /api/share-links/{share_link_id}` | sharing.public |
| `GET /api/statistics/overview` | meetings.read |
| `GET /api/storage/usage` | settings.manage |
| `PATCH /api/stored-files/{stored_file_id}/capture-correction` | photos.manage |
| `PATCH /api/stored-files/{stored_file_id}/capture-date` | photos.manage |
| `GET /api/stored-files/{stored_file_id}/content` | meetings.read |
| `GET /api/stored-files/{stored_file_id}/download` | meetings.read |
| `GET /api/stored-files/{stored_file_id}/metadata` | meetings.read |
| `PATCH /api/stored-files/{stored_file_id}/name` | <P.PHOTOS_MANAGE if (stored_file.mime_type or '').startswith('image/') else P.FILES_MANAGE> + files.manage oder photos.manage |
| `PATCH /api/stored-files/{stored_file_id}/tags` | <P.PHOTOS_MANAGE if (stored_file.mime_type or '').startswith('image/') else P.FILES_MANAGE> + files.manage oder photos.manage |
| `GET /api/stored-files/{stored_file_id}/thumbnail` | meetings.read |
| `GET /api/submission-assignments` | submissions.read |
| `POST /api/submission-assignments` | submissions.manage |
| `GET /api/submission-assignments/reviewer-candidates` | submissions.manage |
| `GET /api/submission-assignments/summaries` | submissions.read |
| `DELETE /api/submission-assignments/{assignment_id}` | submissions.manage |
| `PATCH /api/submission-assignments/{assignment_id}` | submissions.manage |
| `POST /api/submission-assignments/{assignment_id}/delete` | submissions.manage |
| `GET /api/submission-assignments/{assignment_id}/deletion-preview` | submissions.manage |
| `GET /api/submission-assignments/{assignment_id}/download-zip` | submissions.read |
| `GET /api/submission-assignments/{assignment_id}/elements` | submissions.read |
| `POST /api/submission-assignments/{assignment_id}/elements/{element_ref}/close` | submissions.review |
| `POST /api/submission-assignments/{assignment_id}/elements/{element_ref}/reopen` | submissions.review |
| `POST /api/submission-assignments/{assignment_id}/elements/{element_ref}/restore-withdrawn` | submissions.manage |
| `POST /api/submission-assignments/{assignment_id}/rescan-pending` | submissions.manage |
| `GET /api/submission-assignments/{assignment_id}/summary` | submissions.read |
| `GET /api/submission-assignments/{assignment_id}/upload-log` | submissions.read |
| `GET /api/submission-links` | submissions.manage |
| `POST /api/submission-links` | sharing.public, submissions.manage |
| `DELETE /api/submission-links/{link_id}` | sharing.public, submissions.manage |
| `PATCH /api/submission-links/{link_id}` | submissions.manage |
| `POST /api/submission-links/{link_id}/regenerate` | sharing.public, submissions.manage |
| `DELETE /api/submission-uploads/{upload_id}` | submissions.manage |
| `DELETE /api/submission-uploads/{upload_id}/files/{file_id}` | submissions.manage |
| `GET /api/submission-uploads/{upload_id}/files/{file_id}/content` | submissions.read |
| `GET /api/submission-uploads/{upload_id}/files/{file_id}/metadata` | submissions.read |
| `PATCH /api/submission-uploads/{upload_id}/files/{file_id}/tags` | submissions.manage |
| `GET /api/submission-uploads/{upload_id}/files/{file_id}/thumbnail` | submissions.read |
| `GET /api/system-status/summary` | Status-Token (kein Benutzer) |
| `GET /api/table-snapshots/cycles` | meetings.edit |
| `POST /api/table-snapshots/{cycle_config_id}/{cycle_year}/lists/{list_public_id}/reconstruct` | meetings.edit |
| `GET /api/table-snapshots/{cycle_config_id}/{cycle_year}/lists/{list_public_id}/reconstruct-draft` | meetings.edit |
| `GET /api/table-snapshots/{cycle_config_id}/{cycle_year}/{table_name}` | meetings.edit |
| `DELETE /api/table-snapshots/{cycle_config_id}/{cycle_year}/{table_name}/rows/{row_public_id}` | templates.manage |
| `PUT /api/table-snapshots/{cycle_config_id}/{cycle_year}/{table_name}/rows/{row_public_id}` | templates.manage |
| `GET /api/tag-config` | meetings.read |
| `PATCH /api/tag-config` | templates.manage |
| `GET /api/task-packages` | templates.manage · Feature task_packages (lesen) |
| `POST /api/task-packages` | templates.manage · Feature task_packages |
| `DELETE /api/task-packages/{package_id}` | templates.manage · Feature task_packages |
| `GET /api/task-packages/{package_id}` | templates.manage · Feature task_packages (lesen) |
| `PUT /api/task-packages/{package_id}` | templates.manage · Feature task_packages |
| `POST /api/task-packages/{package_id}/cycles` | templates.manage · Feature task_packages |
| `DELETE /api/task-packages/{package_id}/cycles/{package_cycle_id}` | templates.manage · Feature task_packages |
| `PATCH /api/task-packages/{package_id}/cycles/{package_cycle_id}` | templates.manage · Feature task_packages |
| `POST /api/task-packages/{package_id}/items` | templates.manage · Feature task_packages |
| `POST /api/task-packages/{package_id}/items/reorder` | templates.manage · Feature task_packages |
| `DELETE /api/task-packages/{package_id}/items/{item_id}` | templates.manage · Feature task_packages |
| `PUT /api/task-packages/{package_id}/items/{item_id}` | templates.manage · Feature task_packages |
| `GET /api/task-packages/{package_id}/preview` | templates.manage · Feature task_packages (lesen) |
| `POST /api/task-packages/{package_id}/sync` | templates.manage · Feature task_packages |
| `DELETE /api/template-elements/{template_element_id}` | templates.edit |
| `PATCH /api/template-elements/{template_element_id}` | templates.edit |
| `PATCH /api/template-elements/{template_element_id}/behavior` | templates.edit |
| `POST /api/template-elements/{template_element_id}/detach` | templates.edit |
| `GET /api/templates` | meetings.read |
| `POST /api/templates` | templates.manage |
| `DELETE /api/templates/{template_id}` | templates.manage |
| `GET /api/templates/{template_id}` | meetings.read |
| `PATCH /api/templates/{template_id}` | templates.manage |
| `POST /api/templates/{template_id}/duplicate` | templates.manage |
| `GET /api/templates/{template_id}/elements` | meetings.read |
| `POST /api/templates/{template_id}/elements` | templates.edit |
| `GET /api/templates/{template_id}/fine-tariff` | templates.manage · Feature finance |
| `PUT /api/templates/{template_id}/fine-tariff` | templates.manage · Feature finance |
| `GET /api/templates/{template_id}/participants` | participants.manage |
| `PUT /api/templates/{template_id}/participants` | participants.manage |
| `GET /api/tenant-data-exports` | data.export |
| `POST /api/tenant-data-exports` | data.export |
| `GET /api/tenant-data-exports/{export_id}/download` | data.export |
| `GET /api/tenants` | TenantService._manageable_tenant_ids (settings.manage) |
| `GET /api/tenants/lookup` | photos.manage |
| `GET /api/tenants/trusted` | photos.manage |
| `PATCH /api/tenants/{tenant_id}` | TenantService (settings.manage) |
| `GET /api/tenants/{tenant_id}/charges` | TenantService (settings.manage) |
| `GET /api/tenants/{tenant_id}/domains` | TenantService (settings.manage) |
| `POST /api/tenants/{tenant_id}/domains` | TenantService.require_manageable (settings.manage) |
| `DELETE /api/tenants/{tenant_id}/domains/{domain_id}` | TenantService.require_manageable (settings.manage) |
| `POST /api/tenants/{tenant_id}/domains/{domain_id}/verify` | TenantService.require_manageable (settings.manage) |
| `GET /api/tenants/{tenant_id}/profile-image` | Vereinslogo (auch für die Login-Seite) |
| `GET /api/tenants/{tenant_id}/subscription` | TenantService (settings.manage) |
| `GET /api/todo-fines` | eigene Pendenzen-Bussen; alle nur mit reports.personal (im Rumpf) · Feature todo_fines (lesen) |
| `GET /api/todo-fines/filter-options` | fines.manage · Feature todo_fines |
| `GET /api/todo-fines/rules` | finances.read · Feature todo_fines (lesen) |
| `POST /api/todo-fines/rules` | fines.manage · Feature todo_fines |
| `PUT /api/todo-fines/rules/order` | fines.manage · Feature todo_fines |
| `DELETE /api/todo-fines/rules/{rule_id}` | fines.manage · Feature todo_fines |
| `PUT /api/todo-fines/rules/{rule_id}` | fines.manage · Feature todo_fines |
| `GET /api/todo-fines/tariff-members` | fines.manage · Feature finance |
| `PUT /api/todo-fines/tariff-members` | fines.manage · Feature finance |
| `PUT /api/todo-fines/tariff-members/{participant_id}` | fines.manage · Feature finance |
| `GET /api/todo-fines/tariffs` | finances.read · Feature finance (lesen) |
| `POST /api/todo-fines/tariffs` | fines.manage · Feature finance |
| `PUT /api/todo-fines/tariffs/order` | fines.manage · Feature finance |
| `DELETE /api/todo-fines/tariffs/{tariff_id}` | fines.manage · Feature finance |
| `PUT /api/todo-fines/tariffs/{tariff_id}` | fines.manage · Feature finance |
| `POST /api/todo-fines/{fine_id}/collect` | fines.manage · Feature finance, todo_fines |
| `POST /api/todo-fines/{fine_id}/reopen` | fines.manage · Feature todo_fines |
| `POST /api/todo-fines/{fine_id}/restore` | fines.manage · Feature todo_fines |
| `POST /api/todo-fines/{fine_id}/waive` | fines.manage · Feature todo_fines |
| `GET /api/todos` | meetings.read |
| `POST /api/todos` | meetings.edit |
| `GET /api/todos/blocks` | meetings.read |
| `GET /api/todos/my` | meetings.read |
| `POST /api/tools/word-import/analyze` | meetings.edit |
| `POST /api/tools/word-import/commit` | meetings.approve, meetings.edit · je nach Fall: participants.manage |
| `GET /api/tools/word-import/documents` | meetings.edit |
| `POST /api/tools/word-import/documents` | meetings.edit |
| `DELETE /api/tools/word-import/documents/{document_id}` | meetings.edit |
| `GET /api/tools/word-import/documents/{document_id}` | meetings.edit |
| `POST /api/tools/word-import/documents/{document_id}/commit` | meetings.approve, meetings.edit · je nach Fall: participants.manage |
| `PUT /api/tools/word-import/documents/{document_id}/draft` | meetings.edit |
| `POST /api/tools/word-import/documents/{document_id}/reanalyze` | meetings.edit |
| `GET /api/tools/word-import/last-template` | meetings.edit |
| `PUT /api/tools/word-import/last-template` | meetings.edit |
| `GET /api/users` | UserService (access.manage) |
| `POST /api/users` | UserService (access.manage) |
| `GET /api/users/me` | eigenes Konto |
| `PATCH /api/users/me` | eigenes Konto |
| `GET /api/users/me/mfa` | eigene MFA |
| `DELETE /api/users/me/mfa/factors/{factor_id}` | eigene MFA |
| `POST /api/users/me/mfa/passkeys/complete` | eigene MFA |
| `POST /api/users/me/mfa/passkeys/start` | eigene MFA |
| `PATCH /api/users/me/mfa/preferred-method` | eigene MFA |
| `POST /api/users/me/mfa/totp/complete` | eigene MFA |
| `POST /api/users/me/mfa/totp/start` | eigene MFA |
| `GET /api/users/me/notification-preferences` | eigene E-Mail-Benachrichtigungen |
| `PUT /api/users/me/notification-preferences` | eigene E-Mail-Benachrichtigungen |
| `POST /api/users/me/password` | eigenes Passwort |
| `POST /api/users/me/personal-data` | eigene Datenauskunft (rate-limitiert) |
| `GET /api/users/mfa-policy` | access.manage |
| `PUT /api/users/mfa-policy` | access.manage |
| `GET /api/users/protocol-policy` | settings.manage |
| `PUT /api/users/protocol-policy` | settings.manage |
| `DELETE /api/users/{user_id}` | UserService (access.manage) |
| `GET /api/users/{user_id}` | UserService (access.manage) |
| `PATCH /api/users/{user_id}` | UserService (access.manage) |
| `GET /api/users/{user_id}/access-preview` | access.manage |
| `GET /api/users/{user_id}/mfa` | MfaService._managed_user (access.manage) |
| `DELETE /api/users/{user_id}/mfa/factors/{factor_id}` | MfaService._managed_user (access.manage) |
| `PUT /api/users/{user_id}/roles` | access.manage |
| `WEBSOCKET /api/ws/protocols/{protocol_id}` | WebSocket: can_read_protocol beim Verbinden und alle 30 s, Schreiben nur mit meetings.edit (_can_edit) |
