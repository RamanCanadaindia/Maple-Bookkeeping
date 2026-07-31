CREATE TABLE IF NOT EXISTS clients (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT,
    business_name TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reminder_settings (
    id SERIAL PRIMARY KEY,
    resend_api_key TEXT,
    resend_from_email TEXT DEFAULT 'reminders@ramanfinancialservices.ca'
);

CREATE TABLE IF NOT EXISTS reminder_types (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    default_days_before TEXT NOT NULL DEFAULT '30,14,7,2'
);

CREATE TABLE IF NOT EXISTS email_templates (
    id SERIAL PRIMARY KEY,
    reminder_type_id INTEGER NOT NULL REFERENCES reminder_types(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_html TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    reminder_type_id INTEGER NOT NULL REFERENCES reminder_types(id),
    first_due_date TEXT NOT NULL,
    frequency TEXT NOT NULL DEFAULT 'Annually',
    status TEXT NOT NULL DEFAULT 'Active'
);

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    reminder_id INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,
    current_due_date TEXT NOT NULL,
    offset_days INTEGER NOT NULL,
    scheduled_send_date TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending',
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS email_histories (
    id SERIAL PRIMARY KEY,
    reminder_id INTEGER REFERENCES notifications(id) ON DELETE SET NULL,
    recipient_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    status TEXT NOT NULL,
    gmail_message_id TEXT,
    error_message TEXT
);
