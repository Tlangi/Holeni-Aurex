USE [ForexSaas];
GO

/* Required only for migrations that add foreign keys inside the app schema. */
GRANT REFERENCES ON SCHEMA::[app] TO [ForexSaasApp];
GO

SELECT HAS_PERMS_BY_NAME(N'app', N'SCHEMA', N'REFERENCES') AS can_reference_app_schema;
GO
