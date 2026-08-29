USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.macro_sources',N'U') IS NULL
    BEGIN
        CREATE TABLE app.macro_sources
        (
            macro_source_id uniqueidentifier NOT NULL CONSTRAINT PK_macro_sources PRIMARY KEY,
            source_code varchar(50) NOT NULL,
            institution nvarchar(120) NOT NULL,
            currency char(3) NOT NULL,
            evidence_type varchar(30) NOT NULL,
            source_url nvarchar(500) NOT NULL,
            official_host varchar(150) NOT NULL,
            parser_kind varchar(20) NOT NULL,
            priority tinyint NOT NULL CONSTRAINT DF_macro_source_priority DEFAULT 5,
            poll_seconds int NOT NULL CONSTRAINT DF_macro_source_poll DEFAULT 900,
            enabled bit NOT NULL CONSTRAINT DF_macro_source_enabled DEFAULT 1,
            last_attempt_at_utc datetime2(3) NULL,
            last_success_at_utc datetime2(3) NULL,
            last_http_status int NULL,
            last_error_code varchar(80) NULL,
            etag nvarchar(300) NULL,
            last_modified nvarchar(200) NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_macro_sources_created DEFAULT SYSUTCDATETIME(),
            updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_macro_sources_updated DEFAULT SYSUTCDATETIME(),
            CONSTRAINT UQ_macro_sources_code UNIQUE(source_code),
            CONSTRAINT CK_macro_sources_currency CHECK(currency IN ('USD','EUR','GBP','JPY')),
            CONSTRAINT CK_macro_sources_type CHECK(evidence_type IN ('CENTRAL_BANK','INFLATION','CALENDAR')),
            CONSTRAINT CK_macro_sources_parser CHECK(parser_kind IN ('RSS','HTML')),
            CONSTRAINT CK_macro_sources_poll CHECK(poll_seconds BETWEEN 300 AND 86400),
            CONSTRAINT CK_macro_sources_priority CHECK(priority BETWEEN 1 AND 10)
        );
    END;

    IF OBJECT_ID(N'app.macro_evidence',N'U') IS NULL
    BEGIN
        CREATE TABLE app.macro_evidence
        (
            macro_evidence_id uniqueidentifier NOT NULL CONSTRAINT PK_macro_evidence PRIMARY KEY,
            macro_source_id uniqueidentifier NOT NULL,
            external_key char(64) NOT NULL,
            title nvarchar(500) NOT NULL,
            canonical_url nvarchar(800) NOT NULL,
            published_at_utc datetime2(3) NULL,
            retrieved_at_utc datetime2(3) NOT NULL,
            content_sha256 char(64) NOT NULL,
            content_excerpt nvarchar(2000) NOT NULL,
            classification varchar(30) NOT NULL,
            currency_score decimal(8,6) NOT NULL,
            impact varchar(10) NOT NULL,
            scheduled_event_at_utc datetime2(3) NULL,
            parser_version varchar(30) NOT NULL,
            metadata_json nvarchar(max) NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_macro_evidence_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_macro_evidence_source FOREIGN KEY(macro_source_id) REFERENCES app.macro_sources(macro_source_id),
            CONSTRAINT UQ_macro_evidence_revision UNIQUE(macro_source_id,external_key,content_sha256),
            CONSTRAINT CK_macro_evidence_class CHECK(classification IN ('HAWKISH','DOVISH','INFLATIONARY','DISINFLATIONARY','SCHEDULED_RISK','NEUTRAL')),
            CONSTRAINT CK_macro_evidence_score CHECK(currency_score BETWEEN -1 AND 1),
            CONSTRAINT CK_macro_evidence_impact CHECK(impact IN ('LOW','MEDIUM','HIGH')),
            CONSTRAINT CK_macro_evidence_json CHECK(metadata_json IS NULL OR ISJSON(metadata_json)=1)
        );
        CREATE INDEX IX_macro_evidence_source_time ON app.macro_evidence(macro_source_id,retrieved_at_utc DESC);
        CREATE INDEX IX_macro_evidence_event_time ON app.macro_evidence(scheduled_event_at_utc) WHERE scheduled_event_at_utc IS NOT NULL;
    END;

    IF OBJECT_ID(N'app.macro_currency_scores',N'U') IS NULL
    BEGIN
        CREATE TABLE app.macro_currency_scores
        (
            macro_currency_score_id uniqueidentifier NOT NULL CONSTRAINT PK_macro_currency_scores PRIMARY KEY,
            currency char(3) NOT NULL,
            as_of_utc datetime2(3) NOT NULL,
            policy_score decimal(8,6) NOT NULL,
            inflation_score decimal(8,6) NOT NULL,
            event_risk_score decimal(8,6) NOT NULL,
            composite_score decimal(8,6) NOT NULL,
            evidence_count int NOT NULL,
            valid_until_utc datetime2(3) NOT NULL,
            evidence_json nvarchar(max) NOT NULL,
            score_version varchar(30) NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_macro_scores_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT CK_macro_scores_currency CHECK(currency IN ('USD','EUR','GBP','JPY')),
            CONSTRAINT CK_macro_scores_range CHECK(policy_score BETWEEN -1 AND 1 AND inflation_score BETWEEN -1 AND 1 AND event_risk_score BETWEEN 0 AND 1 AND composite_score BETWEEN -1 AND 1),
            CONSTRAINT CK_macro_scores_count CHECK(evidence_count>=0),
            CONSTRAINT CK_macro_scores_json CHECK(ISJSON(evidence_json)=1)
        );
        CREATE INDEX IX_macro_scores_latest ON app.macro_currency_scores(currency,as_of_utc DESC);
    END;

    IF OBJECT_ID(N'app.market_decisions',N'U') IS NULL
    BEGIN
        CREATE TABLE app.market_decisions
        (
            market_decision_id uniqueidentifier NOT NULL CONSTRAINT PK_market_decisions PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            candle_id bigint NOT NULL,
            model_version_id uniqueidentifier NULL,
            decision varchar(4) NOT NULL,
            technical_score decimal(8,6) NOT NULL,
            model_score decimal(8,6) NULL,
            macro_score decimal(8,6) NOT NULL,
            event_risk_score decimal(8,6) NOT NULL,
            combined_score decimal(8,6) NOT NULL,
            confidence decimal(8,6) NOT NULL,
            executable bit NOT NULL,
            blocker_code varchar(80) NULL,
            evidence_json nvarchar(max) NOT NULL,
            input_sha256 char(64) NOT NULL,
            decision_version varchar(30) NOT NULL,
            generated_at_utc datetime2(3) NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_market_decisions_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_market_decisions_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_market_decisions_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_market_decisions_candle FOREIGN KEY(candle_id) REFERENCES app.candles(candle_id),
            CONSTRAINT FK_market_decisions_model FOREIGN KEY(model_version_id) REFERENCES app.model_versions(model_version_id),
            CONSTRAINT UQ_market_decisions_input UNIQUE(tenant_id,market_id,input_sha256),
            CONSTRAINT CK_market_decisions_direction CHECK(decision IN ('BUY','SELL','HOLD')),
            CONSTRAINT CK_market_decisions_scores CHECK(technical_score BETWEEN -1 AND 1 AND (model_score IS NULL OR model_score BETWEEN -1 AND 1) AND macro_score BETWEEN -1 AND 1 AND event_risk_score BETWEEN 0 AND 1 AND combined_score BETWEEN -1 AND 1 AND confidence BETWEEN 0 AND 1),
            CONSTRAINT CK_market_decisions_json CHECK(ISJSON(evidence_json)=1)
        );
        CREATE INDEX IX_market_decisions_latest ON app.market_decisions(tenant_id,market_id,generated_at_utc DESC);
    END;

    MERGE app.platform_components AS target
    USING (SELECT CAST('macro_intelligence' AS varchar(40)) component_code,
                  CAST(N'Macro intelligence' AS nvarchar(100)) display_name) AS source
       ON target.component_code=source.component_code
    WHEN MATCHED THEN UPDATE SET display_name=source.display_name
    WHEN NOT MATCHED THEN INSERT(component_code,display_name,status,status_detail,checked_at_utc)
         VALUES(source.component_code,source.display_name,'UNKNOWN',N'Official-source ingestion has not run',SYSUTCDATETIME());

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
