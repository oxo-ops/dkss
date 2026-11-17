-- DRAFT. Apply separately only after review and fixed-DB authorization.
-- No IF NOT EXISTS: preexisting names require inspection, never silent adoption.
BEGIN;
SET LOCAL synchronous_commit = on;
SET LOCAL lock_timeout = '5s';
CREATE TABLE public.dkss_scoped_pilot_trial (
    trial_id VARCHAR(80) PRIMARY KEY CHECK (trial_id = 'approved-388-HARUMICHI-644-count1-generation1'),
    approval_hash VARCHAR(64) NOT NULL,
    pricing_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE public.dkss_scoped_pilot_phase (
    trial_id VARCHAR(80) NOT NULL REFERENCES public.dkss_scoped_pilot_trial(trial_id),
    phase VARCHAR(12) NOT NULL CHECK (phase IN ('count','generation')),
    policy_hash VARCHAR(64) NOT NULL,
    PRIMARY KEY (trial_id,phase)
);
CREATE TABLE public.dkss_scoped_pilot_reservation (
    trial_id VARCHAR(80) NOT NULL,
    phase VARCHAR(12) NOT NULL,
    body_hash VARCHAR(64) NOT NULL,
    amount INTEGER NOT NULL CHECK ((phase='count' AND amount=1) OR (phase='generation' AND amount>0 AND amount<=250000)),
    state VARCHAR(10) NOT NULL CHECK (state IN ('reserved','returned','uncertain')),
    response_hash VARCHAR(64),
    input_tokens INTEGER,
    request_id VARCHAR(128),
    received_at VARCHAR(64),
    PRIMARY KEY (trial_id,phase),
    FOREIGN KEY (trial_id,phase) REFERENCES public.dkss_scoped_pilot_phase(trial_id,phase)
);
COMMIT;
