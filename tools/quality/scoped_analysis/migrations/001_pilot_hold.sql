-- Deployment prerequisite only. NOT executed by the pilot or at import/startup.
-- Stop/drain every old analysis worker before applying and deploying new code.
-- All readers/writers must run the version that enforces this hold before trial.
ALTER TABLE vehicle_karte_analysis ADD COLUMN pilot_hold VARCHAR(64) NULL;
-- Never drop this column or clear a hold to recover an uncertain billed attempt.
-- Reconcile provider outcome + ledger first; explicit operator release required.
