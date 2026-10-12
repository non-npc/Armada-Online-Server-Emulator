-- Fresh schema; Accounts migrates existing databases after SQLite backup.
CREATE TABLE accounts (name TEXT PRIMARY KEY, player_id INTEGER UNIQUE NOT NULL, salt BLOB, password_hash BLOB);
CREATE TABLE characters (
 player_id INTEGER, slot INTEGER, name TEXT UNIQUE COLLATE NOCASE,
 race INTEGER, ship INTEGER, intro_completed INTEGER NOT NULL DEFAULT 0,
 sector INTEGER, position_x INTEGER, position_z INTEGER,
 last_target_x INTEGER, last_target_z INTEGER,
 PRIMARY KEY(player_id,slot)
);

CREATE TABLE character_saves (player_id INTEGER NOT NULL, slot INTEGER NOT NULL, core BLOB NOT NULL, profile BLOB, saved_at TEXT NOT NULL, extra BLOB, PRIMARY KEY(player_id,slot));
