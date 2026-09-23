const path = require('path');
const sqlite3 = require('sqlite3').verbose();
const { open } = require('sqlite');
require('dotenv').config();

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
            <a href="mailto:beedhtaxservices@gmail.com" style="color: #0284c7; text-decoration: none;">
                beedhtaxservices@gmail.com
            </a>
        </p>
        <p style="margin: 5px 0; font-size: 14px;">
            <a href="https://ramanfinancialservices.ca/" style="color: #0284c7; text-decoration: none;">
                ramanfinancialservices.ca
            </a>
        </p>
        <div style="margin-top: 16px;">
            <a href="{{whatsappLink}}" style="margin: 0 8px; color: #16a34a; text-decoration: none; font-size: 13px; font-weight: 700;">
                WhatsApp
            </a>
            <a href="{{instagramLink}}" style="margin: 0 8px; color: #c13584; text-decoration: none; font-size: 13px; font-weight: 700;">
                Instagram
            </a>
            <a href="https://ramanfinancialservices.ca/" style="margin: 0 8px; color: #0284c7; text-decoration: none; font-size: 13px; font-weight: 700;">
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

async function updateTemplates() {
    console.log('--- Updating Email Templates with Official Branding & Logo Configuration ---');

    // 1. Update SQLite Database
    const dbPath = path.join(__dirname, 'reminders.db');
    try {
        const sqliteDb = await open({
            filename: dbPath,
            driver: sqlite3.Database
        });
        await sqliteDb.exec('PRAGMA foreign_keys = ON;');
        const res = await sqliteDb.run('UPDATE email_templates SET body_html = ?', [COMMON_HTML_TEMPLATE]);
        console.log(`[SQLite] Updated email templates successfully (${res.changes} rows updated).`);
        await sqliteDb.close();
    } catch (err) {
        console.warn('[SQLite] Notice:', err.message);
    }

    // 2. Update Supabase if credentials are provided
    if (process.env.SUPABASE_URL && process.env.SUPABASE_KEY) {
        try {
            const { createClient } = require('@supabase/supabase-js');
            const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_KEY);
            const { data, error } = await supabase
                .from('email_templates')
                .update({ body_html: COMMON_HTML_TEMPLATE })
                .neq('id', 0);

            if (error) {
                console.warn('[Supabase] Could not update templates:', error.message);
            } else {
                console.log('[Supabase] Updated email templates successfully.');
            }
        } catch (err) {
            console.warn('[Supabase] Notice:', err.message);
        }
    }

    console.log('Finished updating email templates.');
}

if (require.main === module) {
    updateTemplates();
}

module.exports = { updateTemplates, COMMON_HTML_TEMPLATE };
