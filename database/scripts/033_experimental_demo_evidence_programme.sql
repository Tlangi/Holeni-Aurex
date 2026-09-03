USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.experimental_risk_policies',N'U') IS NULL
    BEGIN
        CREATE TABLE app.experimental_risk_policies
        (
            experimental_risk_policy_id uniqueidentifier NOT NULL CONSTRAINT PK_experimental_risk_policies PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            version int NOT NULL,
            risk_per_trade_pct decimal(8,4) NOT NULL,
            hard_max_risk_per_trade_pct decimal(8,4) NOT NULL,
            daily_loss_limit_pct decimal(8,4) NOT NULL,
            programme_drawdown_limit_pct decimal(8,4) NOT NULL,
            max_daily_losing_trades int NOT NULL,
            max_open_positions int NOT NULL,
            require_stop bit NOT NULL,
            require_target bit NOT NULL,
            require_max_holding_period bit NOT NULL,
            no_automatic_resubmission bit NOT NULL,
            active bit NOT NULL,
            created_by_user_id uniqueidentifier NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_experimental_risk_policy_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_experimental_risk_policy_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_experimental_risk_policy_user FOREIGN KEY(created_by_user_id) REFERENCES app.users(user_id),
            CONSTRAINT UQ_experimental_risk_policy_version UNIQUE(tenant_id,version),
            CONSTRAINT CK_experimental_risk_policy_caps CHECK(
                risk_per_trade_pct>0 AND risk_per_trade_pct<=0.2500 AND
                hard_max_risk_per_trade_pct=0.2500 AND risk_per_trade_pct<=hard_max_risk_per_trade_pct AND
                daily_loss_limit_pct>0 AND daily_loss_limit_pct<=0.5000 AND
                programme_drawdown_limit_pct>0 AND programme_drawdown_limit_pct<=1.0000 AND
                max_daily_losing_trades BETWEEN 1 AND 2 AND max_open_positions=1 AND
                require_stop=1 AND require_target=1 AND require_max_holding_period=1 AND
                no_automatic_resubmission=1)
        );
        CREATE UNIQUE INDEX UX_experimental_risk_policy_active
            ON app.experimental_risk_policies(tenant_id) WHERE active=1;
    END;

    IF OBJECT_ID(N'app.experimental_programmes',N'U') IS NULL
    BEGIN
        CREATE TABLE app.experimental_programmes
        (
            experimental_programme_id uniqueidentifier NOT NULL CONSTRAINT PK_experimental_programmes PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            owner_user_id uniqueidentifier NOT NULL,
            trading_account_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            market_tier tinyint NOT NULL,
            model_version_id uniqueidentifier NOT NULL,
            model_version varchar(30) NOT NULL,
            model_status varchar(30) NOT NULL,
            artifact_path nvarchar(500) NOT NULL,
            artifact_sha256 char(64) NOT NULL,
            research_lineage_id uniqueidentifier NULL,
            feature_version varchar(80) NOT NULL,
            target_version varchar(80) NOT NULL,
            training_data_version varchar(100) NULL,
            experimental_risk_policy_id uniqueidentifier NOT NULL,
            programme_type varchar(40) NOT NULL,
            stage varchar(40) NOT NULL,
            status varchar(30) NOT NULL,
            starts_at_utc datetime2(3) NOT NULL,
            expires_at_utc datetime2(3) NOT NULL,
            max_attempts int NOT NULL,
            max_holding_minutes int NOT NULL,
            armed_by_user_id uniqueidentifier NULL,
            armed_at_utc datetime2(3) NULL,
            paused_at_utc datetime2(3) NULL,
            completed_at_utc datetime2(3) NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_experimental_programme_created DEFAULT SYSUTCDATETIME(),
            row_version rowversion NOT NULL,
            CONSTRAINT FK_experimental_programme_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_experimental_programme_owner FOREIGN KEY(owner_user_id) REFERENCES app.users(user_id),
            CONSTRAINT FK_experimental_programme_account FOREIGN KEY(trading_account_id) REFERENCES app.trading_accounts(trading_account_id),
            CONSTRAINT FK_experimental_programme_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_experimental_programme_model FOREIGN KEY(model_version_id) REFERENCES app.model_versions(model_version_id),
            CONSTRAINT FK_experimental_programme_lineage FOREIGN KEY(research_lineage_id) REFERENCES app.research_lineages(research_lineage_id),
            CONSTRAINT FK_experimental_programme_policy FOREIGN KEY(experimental_risk_policy_id) REFERENCES app.experimental_risk_policies(experimental_risk_policy_id),
            CONSTRAINT FK_experimental_programme_armed_by FOREIGN KEY(armed_by_user_id) REFERENCES app.users(user_id),
            CONSTRAINT CK_experimental_programme_tier CHECK(market_tier IN (1,2)),
            CONSTRAINT CK_experimental_programme_period CHECK(starts_at_utc<expires_at_utc),
            CONSTRAINT CK_experimental_programme_limits CHECK(max_attempts BETWEEN 1 AND 1000 AND max_holding_minutes BETWEEN 5 AND 10080),
            CONSTRAINT CK_experimental_programme_type CHECK(programme_type IN ('INFRASTRUCTURE_CANARY','BROKER_EVIDENCE')),
            CONSTRAINT CK_experimental_programme_stage CHECK(stage IN ('CANARY','FIVE_ORDER_VALIDATION','TEN_ORDER_COST_VALIDATION','THIRTY_ORDER_REGIME_SAMPLE','EXTENDED_EVIDENCE')),
            CONSTRAINT CK_experimental_programme_status CHECK(status IN ('DRAFT','BLOCKED','ARMED','RUNNING','PAUSED','LOSS_LIMIT_REACHED','KILLED','COMPLETED','EXPIRED')),
            CONSTRAINT CK_experimental_programme_arming CHECK((status IN ('ARMED','RUNNING','PAUSED','LOSS_LIMIT_REACHED','KILLED','COMPLETED','EXPIRED') AND armed_by_user_id IS NOT NULL AND armed_at_utc IS NOT NULL) OR status IN ('DRAFT','BLOCKED'))
        );
        CREATE INDEX IX_experimental_programme_tenant_status ON app.experimental_programmes(tenant_id,status,created_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.experimental_risk_ledgers',N'U') IS NULL
    BEGIN
        CREATE TABLE app.experimental_risk_ledgers
        (
            experimental_risk_ledger_id uniqueidentifier NOT NULL CONSTRAINT PK_experimental_risk_ledgers PRIMARY KEY,
            experimental_programme_id uniqueidentifier NOT NULL,
            ledger_date_sast date NOT NULL,
            day_start_equity_zar decimal(19,6) NOT NULL,
            current_equity_zar decimal(19,6) NOT NULL,
            programme_peak_equity_zar decimal(19,6) NOT NULL,
            realized_pnl_zar decimal(19,6) NOT NULL CONSTRAINT DF_experimental_ledger_realized DEFAULT 0,
            unrealized_pnl_zar decimal(19,6) NOT NULL CONSTRAINT DF_experimental_ledger_unrealized DEFAULT 0,
            open_risk_zar decimal(19,6) NOT NULL CONSTRAINT DF_experimental_ledger_open_risk DEFAULT 0,
            cumulative_losses_zar decimal(19,6) NOT NULL CONSTRAINT DF_experimental_ledger_losses DEFAULT 0,
            losing_trades int NOT NULL CONSTRAINT DF_experimental_ledger_losing_trades DEFAULT 0,
            programme_drawdown_pct decimal(12,6) NOT NULL CONSTRAINT DF_experimental_ledger_dd DEFAULT 0,
            status varchar(20) NOT NULL,
            status_reason varchar(100) NULL,
            reconciled_at_utc datetime2(3) NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_experimental_ledger_created DEFAULT SYSUTCDATETIME(),
            updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_experimental_ledger_updated DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_experimental_ledger_programme FOREIGN KEY(experimental_programme_id) REFERENCES app.experimental_programmes(experimental_programme_id),
            CONSTRAINT UQ_experimental_ledger_day UNIQUE(experimental_programme_id,ledger_date_sast),
            CONSTRAINT CK_experimental_ledger_status CHECK(status IN ('CURRENT','BLOCKED','STALE')),
            CONSTRAINT CK_experimental_ledger_values CHECK(day_start_equity_zar>0 AND current_equity_zar>=0 AND programme_peak_equity_zar>0 AND open_risk_zar>=0 AND cumulative_losses_zar>=0 AND losing_trades>=0 AND programme_drawdown_pct>=0)
        );
    END;

    IF OBJECT_ID(N'app.experimental_attempts',N'U') IS NULL
    BEGIN
        CREATE TABLE app.experimental_attempts
        (
            experimental_attempt_id uniqueidentifier NOT NULL CONSTRAINT PK_experimental_attempts PRIMARY KEY,
            experimental_programme_id uniqueidentifier NOT NULL,
            idempotency_key char(64) NOT NULL,
            signal_timestamp_utc datetime2(3) NOT NULL,
            decision_side varchar(4) NOT NULL,
            model_probability decimal(9,8) NULL,
            decision_threshold decimal(9,8) NULL,
            signal_reason nvarchar(500) NULL,
            regime varchar(80) NULL,
            market_session varchar(80) NULL,
            intended_entry decimal(19,8) NULL,
            intended_stop decimal(19,8) NULL,
            intended_target decimal(19,8) NULL,
            intended_holding_minutes int NULL,
            expected_spread decimal(19,8) NULL,
            expected_slippage decimal(19,8) NULL,
            expected_cost_zar decimal(19,6) NULL,
            requested_size decimal(19,8) NULL,
            broker_minimum_size decimal(19,8) NULL,
            calculated_risk_zar decimal(19,6) NULL,
            bid decimal(19,8) NULL,
            ask decimal(19,8) NULL,
            midpoint decimal(19,8) NULL,
            spread_points decimal(19,8) NULL,
            spread_bps decimal(19,8) NULL,
            market_snapshot_at_utc datetime2(3) NULL,
            market_status varchar(40) NULL,
            available_margin_zar decimal(19,6) NULL,
            account_equity_zar decimal(19,6) NULL,
            decision_state varchar(40) NOT NULL,
            reason_code varchar(100) NULL,
            submission_count tinyint NOT NULL CONSTRAINT DF_experimental_attempt_submission_count DEFAULT 0,
            submitted_at_utc datetime2(3) NULL,
            confirmed_at_utc datetime2(3) NULL,
            ig_deal_reference nvarchar(120) NULL,
            ig_deal_id nvarchar(120) NULL,
            broker_rejection_reason nvarchar(200) NULL,
            correlation_id uniqueidentifier NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_experimental_attempt_created DEFAULT SYSUTCDATETIME(),
            updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_experimental_attempt_updated DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_experimental_attempt_programme FOREIGN KEY(experimental_programme_id) REFERENCES app.experimental_programmes(experimental_programme_id),
            CONSTRAINT UQ_experimental_attempt_idempotency UNIQUE(idempotency_key),
            CONSTRAINT CK_experimental_attempt_side CHECK(decision_side IN ('BUY','SELL','HOLD')),
            CONSTRAINT CK_experimental_attempt_probability CHECK(model_probability IS NULL OR model_probability BETWEEN 0 AND 1),
            CONSTRAINT CK_experimental_attempt_submission CHECK(submission_count BETWEEN 0 AND 1),
            CONSTRAINT CK_experimental_attempt_state CHECK(decision_state IN ('EVALUATED','SKIPPED','ELIGIBLE','SUBMITTING','SUBMITTED','CONFIRMED_OPEN','CONFIRMED_REJECTED','CONFIRMED_CLOSED','UNKNOWN_SUBMISSION','RECONCILIATION_MISMATCH'))
        );
        CREATE INDEX IX_experimental_attempt_programme_time ON app.experimental_attempts(experimental_programme_id,created_at_utc DESC);
        CREATE INDEX IX_experimental_attempt_unresolved ON app.experimental_attempts(decision_state) WHERE decision_state IN ('SUBMITTING','SUBMITTED','UNKNOWN_SUBMISSION','RECONCILIATION_MISMATCH','CONFIRMED_OPEN');
    END;

    IF OBJECT_ID(N'app.experimental_observations',N'U') IS NULL
    BEGIN
        CREATE TABLE app.experimental_observations
        (
            experimental_observation_id uniqueidentifier NOT NULL CONSTRAINT PK_experimental_observations PRIMARY KEY,
            experimental_attempt_id uniqueidentifier NOT NULL,
            actual_fill decimal(19,8) NULL,
            confirmation_latency_ms int NULL,
            spread_original decimal(19,8) NULL,
            slippage_original decimal(19,8) NULL,
            cost_currency char(3) NULL,
            spread_zar decimal(19,6) NULL,
            slippage_zar decimal(19,6) NULL,
            total_actual_cost_zar decimal(19,6) NULL,
            conversion_rate decimal(24,10) NULL,
            conversion_source varchar(80) NULL,
            conversion_at_utc datetime2(3) NULL,
            exit_price decimal(19,8) NULL,
            exit_reason varchar(80) NULL,
            holding_seconds int NULL,
            funding_zar decimal(19,6) NULL,
            gross_pnl_zar decimal(19,6) NULL,
            net_pnl_zar decimal(19,6) NULL,
            theoretical_pnl_zar decimal(19,6) NULL,
            theoretical_actual_difference_zar decimal(19,6) NULL,
            evidence_json nvarchar(max) NOT NULL,
            observed_at_utc datetime2(3) NOT NULL CONSTRAINT DF_experimental_observation_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_experimental_observation_attempt FOREIGN KEY(experimental_attempt_id) REFERENCES app.experimental_attempts(experimental_attempt_id),
            CONSTRAINT UQ_experimental_observation_attempt UNIQUE(experimental_attempt_id),
            CONSTRAINT CK_experimental_observation_json CHECK(ISJSON(evidence_json)=1)
        );
    END;

    IF OBJECT_ID(N'app.experimental_reconciliations',N'U') IS NULL
    BEGIN
        CREATE TABLE app.experimental_reconciliations
        (
            experimental_reconciliation_id uniqueidentifier NOT NULL CONSTRAINT PK_experimental_reconciliations PRIMARY KEY,
            experimental_programme_id uniqueidentifier NOT NULL,
            experimental_attempt_id uniqueidentifier NULL,
            recovery_type varchar(30) NOT NULL,
            result varchar(40) NOT NULL,
            local_deal_reference nvarchar(120) NULL,
            broker_deal_reference nvarchar(120) NULL,
            details_json nvarchar(max) NOT NULL,
            correlation_id uniqueidentifier NOT NULL,
            reconciled_at_utc datetime2(3) NOT NULL CONSTRAINT DF_experimental_reconciliation_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_experimental_reconciliation_programme FOREIGN KEY(experimental_programme_id) REFERENCES app.experimental_programmes(experimental_programme_id),
            CONSTRAINT FK_experimental_reconciliation_attempt FOREIGN KEY(experimental_attempt_id) REFERENCES app.experimental_attempts(experimental_attempt_id),
            CONSTRAINT CK_experimental_reconciliation_type CHECK(recovery_type IN ('SUBMISSION','PERIODIC','STARTUP','MANUAL','CLOSE')),
            CONSTRAINT CK_experimental_reconciliation_result CHECK(result IN ('MATCHED','LOCAL_ONLY','BROKER_ONLY','MISMATCH','UNKNOWN','CONFIRMED_OPEN','CONFIRMED_REJECTED','CONFIRMED_CLOSED')),
            CONSTRAINT CK_experimental_reconciliation_json CHECK(ISJSON(details_json)=1)
        );
        CREATE INDEX IX_experimental_reconciliation_programme ON app.experimental_reconciliations(experimental_programme_id,reconciled_at_utc DESC);
    END;

    /* The task explicitly defines this conservative policy. Creating it does not
       enable the feature flag, arm a programme, or grant broker authority. */
    INSERT app.experimental_risk_policies(
        experimental_risk_policy_id,tenant_id,version,risk_per_trade_pct,
        hard_max_risk_per_trade_pct,daily_loss_limit_pct,programme_drawdown_limit_pct,
        max_daily_losing_trades,max_open_positions,require_stop,require_target,
        require_max_holding_period,no_automatic_resubmission,active)
    SELECT NEWID(),t.tenant_id,1,0.1000,0.2500,0.5000,1.0000,2,1,1,1,1,1,1
    FROM app.tenants t
    WHERE NOT EXISTS(SELECT 1 FROM app.experimental_risk_policies p WHERE p.tenant_id=t.tenant_id);

    COMMIT TRANSACTION;
    PRINT 'Experimental Demo evidence programme migration completed. Feature flag remains configuration-disabled.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
