require('dotenv').config();
const sqlite3 = require('sqlite3');
const { open } = require('sqlite');
const path = require('path');
const fs = require('fs');
const { createClient } = require('@supabase/supabase-js');

let DB_PATH = path.join(__dirname, 'reminders.db');
let dbConnection = null;

class SupabaseAdapter {
    constructor(url, key) {
        this.client = createClient(url, key);
        this.isSupabase = true;
    }

    async get(sql, params = []) {
        const rows = await this.all(sql, params);
        if (!rows || rows.length === 0) {
            if (/COUNT/i.test(sql)) return { count: 0 };
            return undefined;
        }
        return rows[0];
    }

    async all(sql, params = []) {
        const cleanSql = sql.trim().replace(/\s+/g, ' ');
        const isCount = /^SELECT\s+COUNT/i.test(cleanSql);

        // 1. Settings
        if (/FROM settings/i.test(cleanSql) || /FROM reminder_settings/i.test(cleanSql)) {
            const { data, error } = await this.client.from('reminder_settings').select('*');
            if (error) throw new Error(error.message);
            const list = (data || []).map(r => ({
                id: r.id,
                resend_api_key: r.resend_api_key,
                resend_from_email: r.resend_from_email || 'reminders@ramanfinancialservices.ca'
            }));
            return isCount ? [{ count: list.length }] : list;
        }

        // 2. Reminder Types
        if (/FROM reminder_types/i.test(cleanSql)) {
            let query = this.client.from('reminder_types').select('*');
            if (/WHERE id = \?/i.test(cleanSql) && params.length > 0) {
                query = query.eq('id', params[0]);
            }
            if (/WHERE code = \?/i.test(cleanSql) && params.length > 0) {
                query = query.eq('code', params[0]);
            }
            const { data, error } = await query;
            if (error) throw new Error(error.message);
            const list = (data || []).map(r => ({
                id: r.id,
                name: r.name,
                code: r.code,
                default_offsets: r.default_days_before || '30,14,7,2'
            }));
            return isCount ? [{ count: list.length }] : list;
        }

        // 3. Email Templates
        if (/FROM email_templates/i.test(cleanSql)) {
            let query = this.client.from('email_templates').select('*');
            if (/WHERE reminder_type_id = \?/i.test(cleanSql) && params.length > 0) {
                query = query.eq('reminder_type_id', params[0]);
            }
            if (/WHERE id = \?/i.test(cleanSql) && params.length > 0) {
                query = query.eq('id', params[0]);
            }
            const { data, error } = await query;
            if (error) throw new Error(error.message);
            const list = data || [];
            return isCount ? [{ count: list.length }] : list;
        }

        // 4. Clients
        if (/FROM clients/i.test(cleanSql)) {
            let query = this.client.from('clients').select('*');
            if (/WHERE id = \?/i.test(cleanSql) && params.length > 0) {
                query = query.eq('id', params[0]);
            }
            const { data, error } = await query;
            if (error) throw new Error(error.message);

            const { data: rems } = await this.client.from('reminders').select('client_id');
            const remCountMap = new Map();
            (rems || []).forEach(rem => {
                remCountMap.set(rem.client_id, (remCountMap.get(rem.client_id) || 0) + 1);
            });

            const list = (data || []).map(r => ({
                id: r.id,
                name: r.name || r.business_name || 'Client #' + r.id,
                email: r.email || '',
                phone: r.phone || '',
                business_name: r.business_name || '',
                fiscal_year_end: r.fiscal_year_end || '',
                reminders_count: remCountMap.get(r.id) || 0
            }));
            return isCount ? [{ count: list.length }] : list;
        }

        // 5. Reminders
        if (/FROM reminders/i.test(cleanSql)) {
            let query = this.client.from('reminders').select('*');
            if (/WHERE id = \?/i.test(cleanSql) && params.length > 0) {
                query = query.eq('id', params[0]);
            }
            if (/WHERE status = 'Active'/i.test(cleanSql)) {
                query = query.eq('status', 'Active');
            }
            const { data, error } = await query;
            if (error) throw new Error(error.message);
            const list = (data || []).map(r => ({
                id: r.id,
                client_id: r.client_id,
                reminder_type_id: r.reminder_type_id,
                start_due_date: r.first_due_date || r.start_due_date || r.current_due_date,
                frequency: r.frequency || 'Annually',
                status: r.status || 'Active'
            }));
            return isCount ? [{ count: list.length }] : list;
        }

        // 6. Notifications with JOINs
        if (/FROM notifications/i.test(cleanSql)) {
            const { data: notifs, error } = await this.client.from('notifications').select('*');
            if (error) throw new Error(error.message);
            const { data: rems } = await this.client.from('reminders').select('*');
            const { data: cls } = await this.client.from('clients').select('*');
            const { data: rts } = await this.client.from('reminder_types').select('*');

            const remMap = new Map((rems || []).map(r => [r.id, r]));
            const clMap = new Map((cls || []).map(c => [c.id, c]));
            const rtMap = new Map((rts || []).map(t => [t.id, t]));

            let list = (notifs || []).map(n => {
                const rem = remMap.get(n.reminder_id) || {};
                const cl = clMap.get(rem.client_id) || {};
                const rt = rtMap.get(rem.reminder_type_id) || {};

                return {
                    id: n.id,
                    reminder_id: n.reminder_id,
                    due_date: n.current_due_date || n.due_date,
                    offset_days: n.offset_days,
                    send_date: n.scheduled_send_date || n.send_date,
                    recipient_email: n.recipient_email,
                    status: n.status,
                    error_message: n.last_error || n.error_message,
                    client_name: cl.business_name || cl.name || 'Client #' + cl.id,
                    business_name: cl.business_name || cl.name || '',
                    filing_name: rt.name || 'Filing'
                };
            });

            if (/WHERE n.status = 'Pending'/i.test(cleanSql)) {
                list = list.filter(x => x.status === 'Pending');
            }

            return list;
        }

        // 7. Email History
        if (/FROM email_history/i.test(cleanSql) || /FROM email_histories/i.test(cleanSql)) {
            const { data, error } = await this.client.from('email_histories').select('*');
            if (error) throw new Error(error.message);
            const list = (data || []).map(h => ({
                id: h.id,
                notification_id: h.notification_id || h.reminder_id,
                recipient: h.recipient_email || h.recipient,
                subject: h.subject,
                sent_at: h.sent_at,
                status: h.status,
                message_id: h.gmail_message_id || h.message_id,
                error_details: h.error_message || h.error_details
            }));

            if (/GROUP BY status/i.test(cleanSql)) {
                const counts = {};
                for (const item of list) {
                    counts[item.status] = (counts[item.status] || 0) + 1;
                }
                return Object.keys(counts).map(st => ({ status: st, count: counts[st] }));
            }

            return isCount ? [{ count: list.length }] : list;
        }

        return [];
    }

    async run(sql, params = []) {
        const cleanSql = sql.trim().replace(/\s+/g, ' ');

        // Settings update
        if (/UPDATE settings/i.test(cleanSql) || /UPDATE reminder_settings/i.test(cleanSql)) {
            const [key, fromEmail] = params;
            const { error } = await this.client
                .from('reminder_settings')
                .update({ resend_api_key: key, resend_from_email: fromEmail })
                .eq('id', 1);
            if (error) throw new Error(error.message);
            return { lastID: 1, changes: 1 };
        }

        // Insert Client
        if (/INSERT INTO clients/i.test(cleanSql)) {
            const [name, email, phone, business_name, fiscal_year_end] = params;
            const clientName = name || business_name || 'Unnamed Client';
            const { data, error } = await this.client
                .from('clients')
                .insert({
                    name: clientName,
                    business_name: business_name || clientName,
                    email: email || '',
                    phone: phone || '',
                    fiscal_year_end: fiscal_year_end || ''
                })
                .select();
            if (error) throw new Error(error.message);
            return { lastID: data?.[0]?.id || Date.now(), changes: 1 };
        }

        // Update Client
        if (/UPDATE clients/i.test(cleanSql)) {
            const [name, email, phone, business_name, fiscal_year_end, id] = params;
            const clientName = name || business_name || 'Unnamed Client';
            const { error } = await this.client
                .from('clients')
                .update({
                    name: clientName,
                    business_name: business_name || clientName,
                    email: email || '',
                    phone: phone || '',
                    fiscal_year_end: fiscal_year_end || ''
                })
                .eq('id', id);
            if (error) throw new Error(error.message);
            return { lastID: id, changes: 1 };
        }

        // Delete Client
        if (/DELETE FROM clients/i.test(cleanSql)) {
            const [id] = params;
            const { error } = await this.client.from('clients').delete().eq('id', id);
            if (error) throw new Error(error.message);
            return { lastID: id, changes: 1 };
        }

        // Insert Template
        if (/INSERT INTO email_templates/i.test(cleanSql)) {
            const [reminder_type_id, name, subject, body_html] = params;
            const { data, error } = await this.client
                .from('email_templates')
                .insert({ reminder_type_id: parseInt(reminder_type_id, 10), name: name || 'Template', subject, body_html })
                .select();
            if (error) throw new Error(error.message);
            return { lastID: data?.[0]?.id || Date.now(), changes: 1 };
        }

        // Update Template
        if (/UPDATE email_templates/i.test(cleanSql)) {
            if (/WHERE reminder_type_id = \?/i.test(cleanSql)) {
                const [subject, body_html, name, reminder_type_id] = params;
                const updateData = { subject, body_html };
                if (name) updateData.name = name;
                const targetTypeId = parseInt(reminder_type_id, 10);
                const { error } = await this.client
                    .from('email_templates')
                    .update(updateData)
                    .eq('reminder_type_id', targetTypeId);
                if (error) throw new Error(error.message);
                return { lastID: targetTypeId, changes: 1 };
            } else if (/WHERE id = \?/i.test(cleanSql)) {
                let subject, body_html, id;
                if (params.length === 2) {
                    [subject, id] = params;
                } else {
                    [subject, body_html, id] = params;
                }
                const updateData = { subject };
                if (body_html !== undefined) updateData.body_html = body_html;
                const targetId = parseInt(id, 10);
                const { error } = await this.client
                    .from('email_templates')
                    .update(updateData)
                    .eq('id', targetId);
                if (error) throw new Error(error.message);
                return { lastID: targetId, changes: 1 };
            } else {
                const { error } = await this.client
                    .from('email_templates')
                    .update({ body_html: params[0] })
                    .neq('id', 0);
                if (error) throw new Error(error.message);
                return { lastID: 1, changes: 1 };
            }
        }

        // Insert Reminder
        if (/INSERT INTO reminders/i.test(cleanSql)) {
            const [client_id, reminder_type_id, start_due_date, frequency, status] = params;
            const { data, error } = await this.client
                .from('reminders')
                .insert({ client_id, reminder_type_id, first_due_date: start_due_date, frequency, status })
                .select();
            if (error) throw new Error(error.message);
            return { lastID: data?.[0]?.id || Date.now(), changes: 1 };
        }

        // Update Reminder Status
        if (/UPDATE reminders SET status/i.test(cleanSql)) {
            const [status, id] = params;
            const { error } = await this.client.from('reminders').update({ status }).eq('id', id);
            if (error) throw new Error(error.message);
            return { lastID: id, changes: 1 };
        }

        // Delete Reminder
        if (/DELETE FROM reminders/i.test(cleanSql)) {
            const [id] = params;
            const { error } = await this.client.from('reminders').delete().eq('id', id);
            if (error) throw new Error(error.message);
            return { lastID: id, changes: 1 };
        }

        // Insert Notification
        if (/INSERT INTO notifications/i.test(cleanSql)) {
            const [reminder_id, due_date, offset_days, send_date, recipient_email, status, error_message] = params;
            const { data, error } = await this.client
                .from('notifications')
                .insert({
                    reminder_id,
                    current_due_date: due_date,
                    offset_days,
                    scheduled_send_date: send_date,
                    recipient_email,
                    status,
                    last_error: error_message
                })
                .select();
            if (error) throw new Error(error.message);
            return { lastID: data?.[0]?.id || Date.now(), changes: 1 };
        }

        // Update Notification Status
        if (/UPDATE notifications SET status/i.test(cleanSql)) {
            if (params.length === 2) {
                const [status, id] = params;
                await this.client.from('notifications').update({ status }).eq('id', id);
            } else if (params.length === 3) {
                const [st, err, nId] = params;
                await this.client.from('notifications').update({ status: st, last_error: err }).eq('id', nId);
            }
            return { changes: 1 };
        }

        // Insert Email History
        if (/INSERT INTO email_history/i.test(cleanSql) || /INSERT INTO email_histories/i.test(cleanSql)) {
            const [notification_id, recipient, subject, sent_at, status, extra] = params;
            const isSuccess = status === 'Sent';
            const { data, error } = await this.client
                .from('email_histories')
                .insert({
                    reminder_id: notification_id || null,
                    recipient_email: recipient,
                    subject,
                    sent_at,
                    status,
                    gmail_message_id: isSuccess ? extra : null,
                    error_message: !isSuccess ? extra : null
                })
                .select();
            if (error) console.error('Insert email history error:', error.message);
            return { lastID: data?.[0]?.id || Date.now(), changes: 1 };
        }

        return { lastID: 0, changes: 0 };
    }

    async exec(sql) {
        return true;
    }
}

async function getDb() {
    if (dbConnection) return dbConnection;
    
    if (process.env.SUPABASE_URL && process.env.SUPABASE_KEY) {
        console.log('Connecting to Supabase Database...');
        dbConnection = new SupabaseAdapter(process.env.SUPABASE_URL, process.env.SUPABASE_KEY);
        return dbConnection;
    }

    if (process.env.VERCEL) {
        const tmpDbPath = path.join('/tmp', 'reminders.db');
        if (!fs.existsSync(tmpDbPath)) {
            try {
                if (fs.existsSync(DB_PATH)) {
                    fs.copyFileSync(DB_PATH, tmpDbPath);
                }
            } catch (err) {
                console.error('Failed to copy DB to /tmp:', err);
            }
        }
        DB_PATH = tmpDbPath;
    }

    dbConnection = await open({
        filename: DB_PATH,
        driver: sqlite3.Database
    });
    
    // Enable foreign keys
    await dbConnection.exec('PRAGMA foreign_keys = ON;');
    return dbConnection;
}

const COMMON_HTML_TEMPLATE = `<div style="max-width: 620px; margin: 0 auto; background-color: #ffffff; font-family: Arial, Helvetica, sans-serif; color: #1f2937; border: 1px solid #e5e7eb; border-radius: 16px; overflow: hidden;">

    <!-- Header -->
    <div style="background-color: #062b52; padding: 28px 24px; text-align: center;">

        <h1 style="margin: 0; color: #ffffff; font-size: 25px; font-weight: 800; line-height: 1.3;">
            RAMAN TAX &amp; ACCOUNTING INC.
        </h1>

        <p style="margin: 7px 0 0; color: #7dd3fc; font-size: 15px;">
            Trusted. Accurate. Reliable.
        </p>

        <!-- Social and Contact Links -->
        <div style="margin-top: 20px; text-align: center;">

            <a href="{{whatsappLink}}"
               style="display: inline-block; margin: 4px 6px; padding: 9px 14px; background-color: #25D366; color: #ffffff; border-radius: 8px; text-decoration: none; font-size: 13px; font-weight: 700;">
                WhatsApp
            </a>

            <a href="{{instagramLink}}"
               style="display: inline-block; margin: 4px 6px; padding: 9px 14px; background-color: #c13584; color: #ffffff; border-radius: 8px; text-decoration: none; font-size: 13px; font-weight: 700;">
                Instagram
            </a>

            <a href="https://ramanfinancialservices.ca/"
               style="display: inline-block; margin: 4px 6px; padding: 9px 14px; background-color: #0284c7; color: #ffffff; border-radius: 8px; text-decoration: none; font-size: 13px; font-weight: 700;">
                Website
            </a>

        </div>
    </div>

    <!-- Main Content -->
    <div style="padding: 36px 30px; text-align: center;">

        <h2 style="margin: 0 0 16px; color: #062b52; font-size: 28px; font-weight: 800; line-height: 1.3;">
            {{reminderTitle}}
        </h2>

        <p style="margin: 0 0 26px; color: #4b5563; font-size: 16px; line-height: 1.7;">
            Hi <strong>{{clientName}}</strong>, this is a friendly reminder that your
            <strong>{{filingType}}</strong> for
            <strong>{{businessName}}</strong> is approaching.
        </p>

        <!-- Filing Details -->
        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 14px; padding: 22px; text-align: left; margin-bottom: 26px;">

            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse: collapse;">
                <tr>
                    <td style="padding: 8px 0; color: #64748b; font-size: 14px;">
                        Filing type
                    </td>
                    <td style="padding: 8px 0; color: #0f172a; font-size: 14px; font-weight: 700; text-align: right;">
                        {{filingType}}
                    </td>
                </tr>

                <tr>
                    <td style="padding: 8px 0; color: #64748b; font-size: 14px; border-top: 1px solid #e2e8f0;">
                        Reporting period
                    </td>
                    <td style="padding: 8px 0; color: #0f172a; font-size: 14px; font-weight: 700; text-align: right; border-top: 1px solid #e2e8f0;">
                        {{reportingPeriod}}
                    </td>
                </tr>

                <tr>
                    <td style="padding: 8px 0; color: #64748b; font-size: 14px; border-top: 1px solid #e2e8f0;">
                        Due date
                    </td>
                    <td style="padding: 8px 0; color: #dc2626; font-size: 14px; font-weight: 800; text-align: right; border-top: 1px solid #e2e8f0;">
                        {{dueDate}}
                    </td>
                </tr>
            </table>

        </div>

        <!-- Message -->
        <p style="margin: 0 0 22px; color: #4b5563; font-size: 15px; line-height: 1.7;">
            Please send us the required information and documents before the deadline.
            Timely filing can help avoid penalties, interest and unnecessary delays.
        </p>

        <!-- Action Button -->
        <a href="mailto:beedhtaxservices@gmail.com?subject={{emailSubject}}"
           style="background-color: #062b52; color: #ffffff !important; padding: 17px 36px; border-radius: 10px; text-decoration: none; font-weight: 800; display: inline-block; font-size: 15px;">
            Send Documents or Reply
        </a>

        <p style="margin: 18px 0 0; color: #64748b; font-size: 13px; line-height: 1.6;">
            You may reply directly to this email or contact us through WhatsApp.
        </p>

    </div>

    <!-- Contact Section -->
    <div style="background-color: #f8fafc; padding: 24px; text-align: center; border-top: 1px solid #e5e7eb;">

        <p style="margin: 0 0 8px; color: #062b52; font-size: 16px; font-weight: 800;">
            Raman Tax &amp; Accounting Inc.
        </p>

        <p style="margin: 5px 0; font-size: 14px;">
            <a href="mailto:beedhtaxservices@gmail.com"
               style="color: #0284c7; text-decoration: none;">
                beedhtaxservices@gmail.com
            </a>
        </p>

        <p style="margin: 5px 0; font-size: 14px;">
            <a href="https://ramanfinancialservices.ca/"
               style="color: #0284c7; text-decoration: none;">
                ramanfinancialservices.ca
            </a>
        </p>

        <div style="margin-top: 16px;">
            <a href="{{whatsappLink}}"
               style="margin: 0 8px; color: #16a34a; text-decoration: none; font-size: 13px; font-weight: 700;">
                WhatsApp
            </a>

            <a href="{{instagramLink}}"
               style="margin: 0 8px; color: #c13584; text-decoration: none; font-size: 13px; font-weight: 700;">
                Instagram
            </a>

            <a href="https://ramanfinancialservices.ca/"
               style="margin: 0 8px; color: #0284c7; text-decoration: none; font-size: 13px; font-weight: 700;">
                Website
            </a>
        </div>

    </div>

    <!-- Footer -->
    <div style="background-color: #062b52; padding: 18px 24px; text-align: center;">

        <p style="margin: 0 0 6px; color: #ffffff; font-size: 12px;">
            © 2026 Raman Tax &amp; Accounting Inc. All rights reserved.
        </p>

        <p style="margin: 0; color: #bae6fd; font-size: 11px; line-height: 1.5;">
            This is an automated reminder. If you have already submitted your documents or completed the filing, please disregard this email.
        </p>

    </div>

</div>`;

async function initDb() {
    const db = await getDb();
    
    // Check if we need to migrate/re-seed to the new Raman Tax common template format
    let hasGst = false;
    try {
        const row = await db.get("SELECT id FROM reminder_types WHERE code = 'GST_HST'");
        hasGst = !!row;
    } catch (err) {
        // Table doesn't exist yet, we will seed it
        hasGst = false;
    }
    
    // Let's force a migration if the template subject list has old formatting, includes the calendar icon, or contains the old logoUrl image tag
    let forceReSeed = !hasGst;
    if (hasGst) {
        try {
            const gstTemplate = await db.get("SELECT subject, body_html FROM email_templates WHERE reminder_type_id = (SELECT id FROM reminder_types WHERE code = 'GST_HST') LIMIT 1");
            if (gstTemplate && (gstTemplate.subject.includes('30:Reminder') || gstTemplate.body_html.includes('📅') || gstTemplate.body_html.includes('logoUrl'))) {
                forceReSeed = true;
            }
        } catch (err) {
            forceReSeed = true;
        }
    }
    
    if (forceReSeed) {
        console.log("Migrating database reminder types and templates to new Raman Tax design format...");
        // Drop existing tables to start clean with new seeding
        await db.exec(`
            DROP TABLE IF EXISTS email_history;
            DROP TABLE IF EXISTS notifications;
            DROP TABLE IF EXISTS reminders;
            DROP TABLE IF EXISTS email_templates;
            DROP TABLE IF EXISTS reminder_types;
        `);
    }
    
    // Create tables
    await db.exec(`
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            business_name TEXT
        );

        CREATE TABLE IF NOT EXISTS reminder_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            default_offsets TEXT NOT NULL DEFAULT '30,14,7,2'
        );

        CREATE TABLE IF NOT EXISTS email_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reminder_type_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            subject TEXT NOT NULL,
            body_html TEXT NOT NULL,
            FOREIGN KEY (reminder_type_id) REFERENCES reminder_types(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            reminder_type_id INTEGER NOT NULL,
            start_due_date TEXT NOT NULL, -- YYYY-MM-DD
            frequency TEXT NOT NULL DEFAULT 'Annually', -- Monthly, Quarterly, Annually, Custom
            status TEXT NOT NULL DEFAULT 'Active', -- Active, Paused
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE,
            FOREIGN KEY (reminder_type_id) REFERENCES reminder_types(id)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reminder_id INTEGER NOT NULL,
            due_date TEXT NOT NULL, -- YYYY-MM-DD
            offset_days INTEGER NOT NULL,
            send_date TEXT NOT NULL, -- YYYY-MM-DD
            recipient_email TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending', -- Pending, Sent, Failed
            error_message TEXT,
            FOREIGN KEY (reminder_id) REFERENCES reminders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS email_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notification_id INTEGER,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            sent_at TEXT NOT NULL, -- ISO timestamp
            status TEXT NOT NULL, -- Sent, Failed
            message_id TEXT,
            error_details TEXT,
            FOREIGN KEY (notification_id) REFERENCES notifications(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resend_api_key TEXT,
            resend_from_email TEXT DEFAULT 'beedhtaxservices@gmail.com'
        );
    `);
    
    await seedDb(db);
}

async function seedDb(db) {
    // Seed Settings
    const settingCount = await db.get('SELECT COUNT(*) as count FROM settings');
    if (settingCount.count === 0) {
        await db.run('INSERT INTO settings (resend_api_key, resend_from_email) VALUES (NULL, "reminders@ramanfinancialservices.ca")');
    } else {
        const currentSetting = await db.get('SELECT id, resend_from_email FROM settings LIMIT 1');
        if (currentSetting && (currentSetting.resend_from_email === 'onboarding@resend.dev' || currentSetting.resend_from_email === 'beedhtaxservices@gmail.com')) {
            await db.run('UPDATE settings SET resend_from_email = ? WHERE id = ?', ['reminders@ramanfinancialservices.ca', currentSetting.id]);
        }
    }
    
    // Seed Reminder Types
    const typeCount = await db.get('SELECT COUNT(*) as count FROM reminder_types');
    if (typeCount.count === 0) {
        // 1. GST/HST Return (Offsets: 30, 14, 7, 3, 0, -1)
        const r1 = await db.run('INSERT INTO reminder_types (name, code, default_offsets) VALUES (?, ?, ?)', 
            'GST/HST Return', 'GST_HST', '30,14,7,3,0,-1');
        const r1_id = r1.lastID;
        
        // 2. Payroll (Offsets: 30, 7, 3, 0, -1)
        const r2 = await db.run('INSERT INTO reminder_types (name, code, default_offsets) VALUES (?, ?, ?)', 
            'Payroll Remittance', 'PAYROLL', '30,7,3,0,-1');
        const r2_id = r2.lastID;
        
        // 3. BC Annual Report (Offsets: 30, 14, 7, 0, -1)
        const r3 = await db.run('INSERT INTO reminder_types (name, code, default_offsets) VALUES (?, ?, ?)', 
            'BC Annual Report', 'BC_ANNUAL', '30,14,7,0,-1');
        const r3_id = r3.lastID;

        // 4. Corporation Tax Return (T2) (Offsets: 30, 14, 7, 0, -1)
        const r4 = await db.run('INSERT INTO reminder_types (name, code, default_offsets) VALUES (?, ?, ?)', 
            'Corporation Tax Return (T2)', 'CORP_TAX_T2', '30,14,7,0,-1');
        const r4_id = r4.lastID;
        
        // Templates Seeding using Common Premium HTML Layout
        
        // GST/HST Template
        await db.run(`INSERT INTO email_templates (reminder_type_id, name, subject, body_html) VALUES (?, ?, ?, ?)`,
            r1_id,
            'GST/HST Return Template',
            'Reminder: GST/HST Return Due {{DueDate}}',
            COMMON_HTML_TEMPLATE
        );
        
        // Payroll Template
        await db.run(`INSERT INTO email_templates (reminder_type_id, name, subject, body_html) VALUES (?, ?, ?, ?)`,
            r2_id,
            'Payroll Remittance Template',
            'Reminder: Payroll Remittance Due {{DueDate}}',
            COMMON_HTML_TEMPLATE
        );
        
        // BC Annual Report Template
        await db.run(`INSERT INTO email_templates (reminder_type_id, name, subject, body_html) VALUES (?, ?, ?, ?)`,
            r3_id,
            'BC Annual Report Template',
            'Reminder: BC Annual Report Due {{DueDate}}',
            COMMON_HTML_TEMPLATE
        );

        // Corporation Tax Return (T2) Template
        await db.run(`INSERT INTO email_templates (reminder_type_id, name, subject, body_html) VALUES (?, ?, ?, ?)`,
            r4_id,
            'Corporation Tax Return (T2) Template',
            'Reminder: Corporation Tax Return Due {{DueDate}}',
            COMMON_HTML_TEMPLATE
        );
    }
    
    // Migration: keep every template subject concise and safe for single-line inputs.
    const reminderTypes = await db.all('SELECT id, code FROM reminder_types');
    const conciseSubjects = {
        GST_HST: 'Reminder: GST/HST Return Due {{DueDate}}',
        PAYROLL: 'Reminder: Payroll Remittance Due {{DueDate}}',
        BC_ANNUAL: 'Reminder: BC Annual Report Due {{DueDate}}',
        CORP_TAX_T2: 'Reminder: Corporation Tax Return Due {{DueDate}}'
    };

    for (const rt of reminderTypes) {
        const template = await db.get('SELECT id, subject FROM email_templates WHERE reminder_type_id = ?', [rt.id]);
        const conciseSubject = conciseSubjects[rt.code];
        if (template && conciseSubject && template.subject !== conciseSubject) {
            await db.run('UPDATE email_templates SET subject = ? WHERE id = ?', [conciseSubject, template.id]);
        }
    }
}

module.exports = {
    getDb,
    initDb
};
