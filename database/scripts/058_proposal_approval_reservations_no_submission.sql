USE [ForexSaas];
GO
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID(N'app.proposal_approval_challenges',N'U') IS NULL
 CREATE TABLE app.proposal_approval_challenges (
  challenge_id uniqueidentifier NOT NULL CONSTRAINT PK_proposal_approval_challenges PRIMARY KEY,
  trade_proposal_id uniqueidentifier NOT NULL,
  tenant_id uniqueidentifier NOT NULL,
  owner_user_id uniqueidentifier NOT NULL,
  token_sha256 binary(32) NOT NULL,
  expires_at_utc datetime2(3) NOT NULL,
  consumed_at_utc datetime2(3) NULL,
  created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_proposal_challenge_created DEFAULT SYSUTCDATETIME(),
  CONSTRAINT FK_proposal_challenge_proposal FOREIGN KEY(trade_proposal_id) REFERENCES app.trade_proposals(trade_proposal_id),
  CONSTRAINT FK_proposal_challenge_owner FOREIGN KEY(owner_user_id) REFERENCES app.users(user_id),
  CONSTRAINT UQ_proposal_challenge_token UNIQUE(token_sha256)
 );
 IF OBJECT_ID(N'app.proposal_approval_reservations',N'U') IS NULL
 CREATE TABLE app.proposal_approval_reservations (
  reservation_id uniqueidentifier NOT NULL CONSTRAINT PK_proposal_approval_reservations PRIMARY KEY,
  trade_proposal_id uniqueidentifier NOT NULL,
  challenge_id uniqueidentifier NOT NULL,
  tenant_id uniqueidentifier NOT NULL,
  owner_user_id uniqueidentifier NOT NULL,
  status varchar(32) NOT NULL CONSTRAINT DF_proposal_reservation_status DEFAULT 'PRE_SUBMISSION_BLOCKED',
  reserved_at_utc datetime2(3) NOT NULL CONSTRAINT DF_proposal_reservation_created DEFAULT SYSUTCDATETIME(),
  CONSTRAINT FK_proposal_reservation_proposal FOREIGN KEY(trade_proposal_id) REFERENCES app.trade_proposals(trade_proposal_id),
  CONSTRAINT FK_proposal_reservation_challenge FOREIGN KEY(challenge_id) REFERENCES app.proposal_approval_challenges(challenge_id),
  CONSTRAINT UQ_proposal_reservation_proposal UNIQUE(trade_proposal_id),
  CONSTRAINT UQ_proposal_reservation_challenge UNIQUE(challenge_id),
  CONSTRAINT CK_proposal_reservation_no_submission CHECK(status='PRE_SUBMISSION_BLOCKED')
 );
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
