USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.forward_shadow_policies', N'U') IS NULL
    BEGIN
        CREATE TABLE app.forward_shadow_policies
        (
            forward_shadow_policy_id uniqueidentifier NOT NULL
                CONSTRAINT PK_forward_shadow_policies PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            policy_version int NOT NULL,
            minimum_closed_trades int NOT NULL,
            minimum_trading_days int NOT NULL,
            minimum_profit_factor decimal(12,6) NOT NULL,
            minimum_expectancy_zar decimal(19,6) NOT NULL,
            maximum_drawdown_pct decimal(12,6) NOT NULL,
            maximum_consecutive_losses int NOT NULL,
            require_cost_evidence bit NOT NULL,
            active bit NOT NULL,
            created_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_forward_shadow_policies_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_forward_shadow_policies_tenant
                FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT UQ_forward_shadow_policy_version UNIQUE(tenant_id,policy_version),
            CONSTRAINT CK_forward_shadow_policy_values CHECK
                (minimum_closed_trades>=20 AND minimum_trading_days>=5
                 AND minimum_profit_factor>=1 AND minimum_expectancy_zar>=0
                 AND maximum_drawdown_pct>0 AND maximum_drawdown_pct<=10
                 AND maximum_consecutive_losses BETWEEN 1 AND 10)
        );
        CREATE UNIQUE INDEX UX_forward_shadow_policy_active
            ON app.forward_shadow_policies(tenant_id) WHERE active=1;
    END;

    INSERT app.forward_shadow_policies
        (forward_shadow_policy_id,tenant_id,policy_version,minimum_closed_trades,
         minimum_trading_days,minimum_profit_factor,minimum_expectancy_zar,
         maximum_drawdown_pct,maximum_consecutive_losses,require_cost_evidence,active)
    SELECT NEWID(),t.tenant_id,1,30,10,1.100000,0,3.000000,4,1,1
    FROM app.tenants t
    WHERE NOT EXISTS
        (SELECT 1 FROM app.forward_shadow_policies p WHERE p.tenant_id=t.tenant_id);

    IF OBJECT_ID(N'app.forward_shadow_evaluations', N'U') IS NULL
    BEGIN
        CREATE TABLE app.forward_shadow_evaluations
        (
            forward_shadow_evaluation_id uniqueidentifier NOT NULL
                CONSTRAINT PK_forward_shadow_evaluations PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            model_version_id uniqueidentifier NOT NULL,
            forward_shadow_policy_id uniqueidentifier NOT NULL,
            evidence_candle_id bigint NOT NULL,
            closed_trades int NOT NULL,
            trading_days int NOT NULL,
            wins int NOT NULL,
            losses int NOT NULL,
            win_rate decimal(12,8) NOT NULL,
            profit_factor decimal(19,8) NULL,
            expectancy_zar decimal(19,6) NOT NULL,
            maximum_drawdown_pct decimal(12,6) NOT NULL,
            maximum_consecutive_losses int NOT NULL,
            cost_evidence_coverage decimal(12,8) NOT NULL,
            realized_pnl_zar decimal(19,6) NOT NULL,
            passed bit NOT NULL,
            blockers_json nvarchar(max) NOT NULL,
            evaluated_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_forward_shadow_evaluations_time DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_forward_shadow_evaluations_tenant
                FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_forward_shadow_evaluations_market
                FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_forward_shadow_evaluations_model
                FOREIGN KEY(model_version_id) REFERENCES app.model_versions(model_version_id),
            CONSTRAINT FK_forward_shadow_evaluations_policy
                FOREIGN KEY(forward_shadow_policy_id)
                    REFERENCES app.forward_shadow_policies(forward_shadow_policy_id),
            CONSTRAINT FK_forward_shadow_evaluations_candle
                FOREIGN KEY(evidence_candle_id) REFERENCES app.candles(candle_id),
            CONSTRAINT UQ_forward_shadow_evaluation_evidence
                UNIQUE(tenant_id,market_id,model_version_id,evidence_candle_id),
            CONSTRAINT CK_forward_shadow_evaluation_json CHECK(ISJSON(blockers_json)=1),
            CONSTRAINT CK_forward_shadow_evaluation_counts CHECK
                (closed_trades>=0 AND trading_days>=0 AND wins>=0 AND losses>=0
                 AND maximum_consecutive_losses>=0),
            CONSTRAINT CK_forward_shadow_evaluation_rates CHECK
                (win_rate BETWEEN 0 AND 1 AND cost_evidence_coverage BETWEEN 0 AND 1
                 AND maximum_drawdown_pct>=0)
        );
        CREATE INDEX IX_forward_shadow_evaluations_latest
            ON app.forward_shadow_evaluations(tenant_id,market_id,evaluated_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.demo_execution_attempts', N'U') IS NULL
    BEGIN
        CREATE TABLE app.demo_execution_attempts
        (
            demo_execution_attempt_id uniqueidentifier NOT NULL
                CONSTRAINT PK_demo_execution_attempts PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            user_id uniqueidentifier NOT NULL,
            order_intent_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            model_version_id uniqueidentifier NOT NULL,
            market_decision_id uniqueidentifier NOT NULL,
            correlation_id uniqueidentifier NOT NULL,
            status varchar(30) NOT NULL,
            submission_count int NOT NULL CONSTRAINT DF_demo_attempt_submission_count DEFAULT 0,
            deal_reference nvarchar(120) NULL,
            deal_id nvarchar(120) NULL,
            failure_code varchar(100) NULL,
            started_at_utc datetime2(3) NOT NULL CONSTRAINT DF_demo_attempt_started DEFAULT SYSUTCDATETIME(),
            completed_at_utc datetime2(3) NULL,
            CONSTRAINT FK_demo_execution_attempts_tenant
                FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_demo_execution_attempts_user
                FOREIGN KEY(user_id) REFERENCES app.users(user_id),
            CONSTRAINT FK_demo_execution_attempts_intent
                FOREIGN KEY(order_intent_id) REFERENCES app.order_intents(order_intent_id),
            CONSTRAINT FK_demo_execution_attempts_market
                FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_demo_execution_attempts_model
                FOREIGN KEY(model_version_id) REFERENCES app.model_versions(model_version_id),
            CONSTRAINT FK_demo_execution_attempts_decision
                FOREIGN KEY(market_decision_id) REFERENCES app.market_decisions(market_decision_id),
            CONSTRAINT UQ_demo_execution_attempt_intent UNIQUE(order_intent_id),
            CONSTRAINT CK_demo_execution_attempt_status CHECK(status IN
                ('RESERVED','SUBMITTING','ACKNOWLEDGED','CONFIRMING','OPEN','REJECTED',
                 'SUBMISSION_UNKNOWN','RECONCILIATION_REQUIRED','FAILED')),
            CONSTRAINT CK_demo_execution_single_submission CHECK(submission_count BETWEEN 0 AND 1)
        );
        CREATE INDEX IX_demo_execution_attempts_tenant_time
            ON app.demo_execution_attempts(tenant_id,started_at_utc DESC);
    END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
