-- ============================================================
-- API Gateway Database Schema & Migrations Combined
-- ============================================================

CREATE DATABASE IF NOT EXISTS api_gateway
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE api_gateway;

-- ------------------------------------------------------------
-- Table: users
-- Stores authenticated mobile app sessions
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                              INT             NOT NULL,
    name                            VARCHAR(255)    DEFAULT NULL,
    user_name                       VARCHAR(255)    DEFAULT NULL,
    tenant_id                       VARCHAR(255)    DEFAULT NULL,
    instance                        VARCHAR(255)    DEFAULT NULL,
    access_token                    VARCHAR(255)    DEFAULT NULL,
    access_token_creation_time      TIMESTAMP       NULL DEFAULT NULL,
    access_token_last_use_time      TIMESTAMP       NULL DEFAULT NULL,
    access_token_expiry_time        TIMESTAMP       NULL DEFAULT NULL,
    refresh_token                   VARCHAR(255)    DEFAULT NULL,
    refresh_token_creation_time     TIMESTAMP       NULL DEFAULT NULL,
    refresh_token_last_use_time     TIMESTAMP       NULL DEFAULT NULL,
    refresh_token_expiry_time       TIMESTAMP       NULL DEFAULT NULL,
    odoo_key                        VARCHAR(255)    DEFAULT NULL,
    roles                           VARCHAR(255)    DEFAULT NULL,
    partner_id                      INT             DEFAULT NULL,

    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_users_access_token  ON users (access_token);
CREATE INDEX idx_users_refresh_token ON users (refresh_token);
CREATE INDEX idx_users_tenant        ON users (tenant_id, instance);

-- ------------------------------------------------------------
-- Table: jobs
-- Tracks scheduled background job state
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
    id                              INT             NOT NULL AUTO_INCREMENT,
    minute_process                  BOOLEAN         NOT NULL DEFAULT FALSE,
    minute_process_last_update      TIMESTAMP       NULL DEFAULT NULL,
    hourly_process                  BOOLEAN         NOT NULL DEFAULT FALSE,
    hourly_process_last_update      TIMESTAMP       NULL DEFAULT NULL,
    midnight_process                BOOLEAN         NOT NULL DEFAULT FALSE,
    midnight_process_last_update    TIMESTAMP       NULL DEFAULT NULL,

    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- Table: device_tokens
-- Stores FCM push notification tokens for mobile devices
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS device_tokens (
    id          INT             NOT NULL AUTO_INCREMENT,
    user_id     INT             NOT NULL,
    tenant_id   VARCHAR(255)    NOT NULL,
    instance    VARCHAR(255)    NOT NULL,
    fcm_token   VARCHAR(512)    NOT NULL,
    platform    VARCHAR(20)     NOT NULL,
    created_at  TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP       DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uq_user_device (user_id, fcm_token),
    INDEX idx_user_tenant (user_id, tenant_id, instance)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
