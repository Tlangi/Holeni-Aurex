USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET ARITHABORT ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET QUOTED_IDENTIFIER ON;
SET NUMERIC_ROUNDABORT OFF;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.model_evaluations', N'U') IS NULL
    BEGIN
        CREATE TABLE app.model_evaluations
        (
            model_evaluation_id uniqueidentifier NOT NULL CONSTRAINT PK_model_evaluations PRIMARY KEY,
            model_version_id uniqueidentifier NOT NULL,
            training_rows int NOT NULL,
            validation_rows int NOT NULL,
            training_start_utc datetime2(3) NOT NULL,
            training_end_utc datetime2(3) NOT NULL,
            validation_start_utc datetime2(3) NOT NULL,
            validation_end_utc datetime2(3) NOT NULL,
            validation_auc decimal(8,6) NULL,
            acceptance_auc decimal(8,6) NOT NULL,
            result varchar(20) NOT NULL,
            failure_reason nvarchar(300) NULL,
            evaluated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_model_evaluations_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_model_evaluations_model FOREIGN KEY(model_version_id)
                REFERENCES app.model_versions(model_version_id),
            CONSTRAINT UQ_model_evaluations_model UNIQUE(model_version_id),
            CONSTRAINT CK_model_evaluations_result CHECK(result IN ('PASSED','REJECTED','FAILED')),
            CONSTRAINT CK_model_evaluations_rows CHECK(training_rows > 0 AND validation_rows > 0)
        );
    END;

    IF OBJECT_ID(N'app.broker_market_rules', N'U') IS NULL
    BEGIN
        CREATE TABLE app.broker_market_rules
        (
            broker_market_rule_id uniqueidentifier NOT NULL CONSTRAINT PK_broker_market_rules PRIMARY KEY,
            broker_connection_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            min_deal_size decimal(19,8) NOT NULL,
            size_increment decimal(19,8) NOT NULL,
            min_stop_distance decimal(19,8) NOT NULL,
            value_per_price_point_zar decimal(19,8) NULL,
            source_currency char(3) NOT NULL,
            observed_at_utc datetime2(3) NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_broker_market_rules_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_broker_market_rules_connection FOREIGN KEY(broker_connection_id)
                REFERENCES app.broker_connections(broker_connection_id),
            CONSTRAINT FK_broker_market_rules_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT UQ_broker_market_rules_market UNIQUE(broker_connection_id,market_id),
            CONSTRAINT CK_broker_market_rules_values CHECK
                (min_deal_size > 0 AND size_increment > 0 AND min_stop_distance > 0
                 AND (value_per_price_point_zar IS NULL OR value_per_price_point_zar > 0))
        );
    END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
