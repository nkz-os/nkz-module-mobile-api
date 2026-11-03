-- Mobile API registration (marketplace_modules). Idempotent; one transaction.
-- Backend-only module (no frontend): remote_entry_url, scope and exposed_module are NULL
-- (allowed since migration 033). Apply on the platform database as a superuser.

\echo '--- before'
SELECT id, version, required_roles, metadata ? 'source_repo' AS publishable
  FROM marketplace_modules WHERE id = 'mobile-api';

BEGIN;

INSERT INTO marketplace_modules (
    id, name, display_name, description, remote_entry_url, scope, exposed_module, version, author,
    category, icon_url, route_path, label, required_plan_level, is_local, is_active,
    required_roles, metadata
) VALUES (
    'mobile-api', 'mobile-api', 'Mobile API',
    'Backend that composes platform data for the mobile app.',
    NULL, NULL, NULL, '0.1.0', 'Nekazari',
    'platform', NULL, NULL, 'Mobile API', 0, false, true,
    ARRAY['Farmer', 'TechnicalConsultant', 'TenantAdmin', 'PlatformAdmin'],
    '{
      "api_prefix": "/api/mobile",
      "backend_service": "http://mobile-api-service:8000",
      "backend_mount": "/api/mobile",
      "requires_auth": true,
      "source_repo": "nkz-os/nkz-module-mobile-api",
      "deploy_method": "backend_only",
      "hostApiVersion": "^2.0.0",
      "description_i18n": {
        "es": "Servicio que compone los datos de la plataforma para la aplicación móvil.",
        "en": "Service that composes platform data for the mobile app.",
        "eu": "Plataformako datuak aplikazio mugikorrerako biltzen dituen zerbitzua."
      }
    }'::jsonb
) ON CONFLICT (id) DO UPDATE SET
    display_name     = EXCLUDED.display_name,
    description      = EXCLUDED.description,
    remote_entry_url = EXCLUDED.remote_entry_url,
    scope            = EXCLUDED.scope,
    exposed_module   = EXCLUDED.exposed_module,
    icon_url         = EXCLUDED.icon_url,
    route_path       = EXCLUDED.route_path,
    label            = EXCLUDED.label,
    required_roles   = EXCLUDED.required_roles,
    is_active        = true,
    metadata         = COALESCE(marketplace_modules.metadata, '{}'::jsonb) || EXCLUDED.metadata,
    updated_at       = NOW();

COMMIT;

\echo '--- after'
SELECT id, version, required_roles,
       metadata->>'api_prefix' AS api_prefix, metadata->>'backend_service' AS backend, metadata->>'source_repo' AS repo
  FROM marketplace_modules WHERE id = 'mobile-api';
