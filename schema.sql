DROP TABLE IF EXISTS contributions;
DROP TABLE IF EXISTS loans;
DROP TABLE IF EXISTS friendships;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    balance REAL DEFAULT 1000.0,
    base_credit_score INTEGER DEFAULT 650, -- Base starting score
    request_filter TEXT DEFAULT 'all' -- 'all', 'friends', 'none'
);

CREATE TABLE friendships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    friend_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (friend_id) REFERENCES users (id)
);

CREATE TABLE loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    borrower_id INTEGER NOT NULL,
    lender_id INTEGER, -- Can be NULL if it's a crowdfunded public loan
    amount REAL NOT NULL,
    amount_funded REAL DEFAULT 0.0, -- Tracks progress of crowdfunding
    interest_rate REAL NOT NULL,
    due_date DATE NOT NULL,
    is_public BOOLEAN DEFAULT 0, -- 1 if it goes to the crowdfunding market
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (borrower_id) REFERENCES users (id),
    FOREIGN KEY (lender_id) REFERENCES users (id)
);
