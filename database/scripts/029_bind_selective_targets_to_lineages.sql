USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH(N'app.research_lineages',N'research_target_spec_id') IS NULL
        ALTER TABLE app.research_lineages ADD research_target_spec_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.research_lineages',N'research_protocol_version') IS NULL
        ALTER TABLE app.research_lineages ADD research_protocol_version varchar(80) NULL;
    IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_research_lineages_target_spec')
        ALTER TABLE app.research_lineages ADD CONSTRAINT FK_research_lineages_target_spec
            FOREIGN KEY(research_target_spec_id) REFERENCES app.research_target_specs(research_target_spec_id);

    IF COL_LENGTH(N'app.research_experiments',N'research_target_spec_id') IS NULL
        ALTER TABLE app.research_experiments ADD research_target_spec_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.research_experiments',N'research_protocol_version') IS NULL
        ALTER TABLE app.research_experiments ADD research_protocol_version varchar(80) NULL;
    IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_research_experiments_target_spec')
        ALTER TABLE app.research_experiments ADD CONSTRAINT FK_research_experiments_target_spec
            FOREIGN KEY(research_target_spec_id) REFERENCES app.research_target_specs(research_target_spec_id);

    COMMIT TRANSACTION;
    PRINT 'Aurex selective target lineage binding migration completed.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
