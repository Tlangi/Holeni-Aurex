USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF EXISTS(SELECT 1 FROM sys.check_constraints WHERE name=N'CK_research_retrain_type'
              AND parent_object_id=OBJECT_ID(N'app.research_experiments'))
        ALTER TABLE app.research_experiments DROP CONSTRAINT CK_research_retrain_type;
    ALTER TABLE app.research_experiments ADD CONSTRAINT CK_research_retrain_type
        CHECK(retrain_type IN ('SCHEDULED_RETRAIN','RESEARCH_RETRAIN','DIAGNOSTIC_REPLAY','HOLDOUT_CANDIDATE'));

    IF OBJECT_ID(N'app.holdout_candidates',N'U') IS NULL
    BEGIN
        CREATE TABLE app.holdout_candidates
        (
            holdout_candidate_id uniqueidentifier NOT NULL CONSTRAINT PK_holdout_candidates PRIMARY KEY,
            experiment_id uniqueidentifier NOT NULL,
            tenant_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            strategy_version_id uniqueidentifier NOT NULL,
            candidate_version varchar(100) NOT NULL,
            feature_version varchar(80) NOT NULL,
            label_version varchar(80) NOT NULL,
            regime_version varchar(80) NOT NULL,
            cost_model_version varchar(80) NOT NULL,
            artifact_path nvarchar(500) NULL,
            artifact_sha256 char(64) NULL,
            configuration_hash char(64) NOT NULL,
            development_data_sha256 char(64) NOT NULL,
            holdout_data_sha256 char(64) NOT NULL,
            development_start_utc datetime2(3) NOT NULL,
            development_end_utc datetime2(3) NOT NULL,
            holdout_start_utc datetime2(3) NOT NULL,
            holdout_end_utc datetime2(3) NOT NULL,
            development_rows int NOT NULL,
            holdout_rows int NOT NULL,
            validation_json nvarchar(max) NOT NULL,
            validation_passed bit NOT NULL,
            status varchar(30) NOT NULL,
            notes nvarchar(1000) NULL,
            frozen_at_utc datetime2(3) NOT NULL CONSTRAINT DF_holdout_candidates_frozen DEFAULT SYSUTCDATETIME(),
            holdout_consumed_at_utc datetime2(3) NULL,
            evaluated_at_utc datetime2(3) NULL,
            CONSTRAINT FK_holdout_candidates_experiment FOREIGN KEY(experiment_id) REFERENCES app.research_experiments(experiment_id),
            CONSTRAINT FK_holdout_candidates_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_holdout_candidates_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_holdout_candidates_strategy FOREIGN KEY(strategy_version_id) REFERENCES app.strategy_versions(strategy_version_id),
            CONSTRAINT UQ_holdout_candidate_version UNIQUE(tenant_id,market_id,candidate_version),
            CONSTRAINT UQ_holdout_candidate_configuration UNIQUE(tenant_id,market_id,configuration_hash,holdout_start_utc,holdout_end_utc),
            CONSTRAINT CK_holdout_candidate_status CHECK(status IN ('FROZEN','VALIDATION_REJECTED','EVALUATING','HOLDOUT_PASSED','HOLDOUT_REJECTED','EVALUATION_FAILED')),
            CONSTRAINT CK_holdout_candidate_rows CHECK(development_rows>=2000 AND holdout_rows>=100),
            CONSTRAINT CK_holdout_candidate_period CHECK(development_start_utc<=development_end_utc AND development_end_utc<holdout_start_utc AND holdout_start_utc<=holdout_end_utc),
            CONSTRAINT CK_holdout_candidate_validation_json CHECK(ISJSON(validation_json)=1),
            CONSTRAINT CK_holdout_candidate_artifact CHECK((status='VALIDATION_REJECTED' AND artifact_path IS NULL AND artifact_sha256 IS NULL) OR (artifact_path IS NOT NULL AND artifact_sha256 IS NOT NULL))
        );
        CREATE INDEX IX_holdout_candidates_market_time ON app.holdout_candidates(market_id,frozen_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.holdout_evaluations',N'U') IS NULL
    BEGIN
        CREATE TABLE app.holdout_evaluations
        (
            holdout_evaluation_id uniqueidentifier NOT NULL CONSTRAINT PK_holdout_evaluations PRIMARY KEY,
            holdout_candidate_id uniqueidentifier NOT NULL,
            result varchar(20) NOT NULL,
            observation_count int NOT NULL,
            trade_count int NOT NULL,
            validation_auc decimal(12,8) NOT NULL,
            brier_score decimal(12,8) NOT NULL,
            calibration_error decimal(12,8) NOT NULL,
            feature_drift_score decimal(12,8) NOT NULL,
            regime_coverage decimal(12,8) NOT NULL,
            win_rate decimal(12,8) NOT NULL,
            profit_factor decimal(19,8) NOT NULL,
            expectancy decimal(19,12) NOT NULL,
            max_drawdown decimal(19,12) NOT NULL,
            baseline_outperformed bit NOT NULL,
            metrics_json nvarchar(max) NOT NULL,
            baselines_json nvarchar(max) NOT NULL,
            regimes_json nvarchar(max) NOT NULL,
            gates_json nvarchar(max) NOT NULL,
            evaluated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_holdout_evaluations_time DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_holdout_evaluations_candidate FOREIGN KEY(holdout_candidate_id) REFERENCES app.holdout_candidates(holdout_candidate_id),
            CONSTRAINT UQ_holdout_evaluations_candidate UNIQUE(holdout_candidate_id),
            CONSTRAINT CK_holdout_evaluation_result CHECK(result IN ('PASSED','REJECTED')),
            CONSTRAINT CK_holdout_evaluation_counts CHECK(observation_count>=100 AND trade_count>=0),
            CONSTRAINT CK_holdout_evaluation_metrics_json CHECK(ISJSON(metrics_json)=1),
            CONSTRAINT CK_holdout_evaluation_baselines_json CHECK(ISJSON(baselines_json)=1),
            CONSTRAINT CK_holdout_evaluation_regimes_json CHECK(ISJSON(regimes_json)=1),
            CONSTRAINT CK_holdout_evaluation_gates_json CHECK(ISJSON(gates_json)=1)
        );
    END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
