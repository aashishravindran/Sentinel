CREATE TABLE IF NOT EXISTS permissions (
    user_id TEXT NOT NULL,
    tag     TEXT NOT NULL,
    PRIMARY KEY (user_id, tag)
);

-- Seed data for local development
-- alice  : finance, public
-- bob    : public, engineering
-- charlie: finance, engineering, public
INSERT OR IGNORE INTO permissions VALUES ('alice',   'finance');
INSERT OR IGNORE INTO permissions VALUES ('alice',   'public');
INSERT OR IGNORE INTO permissions VALUES ('bob',     'public');
INSERT OR IGNORE INTO permissions VALUES ('bob',     'engineering');
INSERT OR IGNORE INTO permissions VALUES ('charlie', 'finance');
INSERT OR IGNORE INTO permissions VALUES ('charlie', 'engineering');
INSERT OR IGNORE INTO permissions VALUES ('charlie', 'public');
