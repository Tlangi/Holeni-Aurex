USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.forward_evidence_snapshots',N'U') IS NULL
    BEGIN
        CREATE TABLE app.forward_evidence_snapshots
        (
            forward_evidence_snapshot_id uniqueidentifier NOT NULL
                CONSTRAINT PK_forward_evidence_snapshots PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            evidence_candle_id bigint NOT NULL,
            model_version_id uniqueidentifier NULL,
            market_decision_id uniqueidentifier NULL,
            evidence_date_sast date NOT NULL,
            first_m15_utc datetime2(3) NULL,
            latest_m15_utc datetime2(3) NOT NULL,
            raw_m15_rows int NOT NULL,
            feature_complete_rows int NOT NULL,
            required_feature_rows int NOT NULL,
            spread_evidence_rows int NOT NULL,
            quality_status varchar(30) NOT NULL,
            model_status varchar(30) NOT NULL,
            market_decision varchar(4) NOT NULL,
            decision_executable bit NOT NULL,
            decision_blocker varchar(80) NULL,
            execution_mode varchar(20) NOT NULL,
            risk_status varchar(30) NOT NULL,
            reconciliation_clear bit NOT NULL,
            shadow_open_count int NOT NULL,
            shadow_closed_count int NOT NULL,
            shadow_win_count int NOT NULL,
            shadow_loss_count int NOT NULL,
            shadow_realized_pnl_zar decimal(19,6) NOT NULL,
            shadow_unrealized_pnl_zar decimal(19,6) NOT NULL,
            evidence_state varchar(30) NOT NULL,
            blockers_json nvarchar(max) NOT NULL,
            captured_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_forward_evidence_captured DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_forward_evidence_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_forward_evidence_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_forward_evidence_candle FOREIGN KEY(evidence_candle_id) REFERENCES app.candles(candle_id),
            CONSTRAINT FK_forward_evidence_model FOREIGN KEY(model_version_id) REFERENCES app.model_versions(model_version_id),
            CONSTRAINT FK_forward_evidence_decision FOREIGN KEY(market_decision_id) REFERENCES app.market_decisions(market_decision_id),
            CONSTRAINT UQ_forward_evidence_market_candle UNIQUE(tenant_id,market_id,evidence_candle_id),
            CONSTRAINT CK_forward_evidence_direction CHECK(market_decision IN ('BUY','SELL','HOLD','NONE')),
            CONSTRAINT CK_forward_evidence_state CHECK(evidence_state IN ('ACCUMULATING','BLOCKED','FORWARD_SHADOW','DEMO_TEST_READY')),
            CONSTRAINT CK_forward_evidence_blockers_json CHECK(ISJSON(blockers_json)=1)
        );
        CREATE INDEX IX_forward_evidence_tenant_time
            ON app.forward_evidence_snapshots(tenant_id,captured_at_utc DESC);
        CREATE INDEX IX_forward_evidence_market_time
            ON app.forward_evidence_snapshots(tenant_id,market_id,latest_m15_utc DESC);
    END;

    COMMIT TRANSACTION;
    PRINT 'Created the market-specific forward-evidence ledger.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
