require('dotenv').config();
const { createClient } = require('@supabase/supabase-js');

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_KEY);

async function fixDates() {
    console.log('Querying clients from Supabase...');
    const { data: clients } = await supabase.from('clients').select('*');

    const golfClient = clients.find(c => (c.business_name || '').toUpperCase().includes('GOLF BALL') || (c.name || '').toUpperCase().includes('GOLF BALL'));
    if (!golfClient) {
        console.log('Golf ball client not found');
        return;
    }

    console.log('Found client:', golfClient.id, golfClient.name);

    // Fetch reminders for this client
    const { data: reminders } = await supabase
        .from('reminders')
        .select('*')
        .eq('client_id', golfClient.id);

    console.log('Client reminders:', reminders);

    for (const rem of (reminders || [])) {
        const dueDate = rem.first_due_date || '';
        const newDueDate = dueDate.replace('2027-', '2026-');
        console.log(`Updating reminder ${rem.id} from ${dueDate} to ${newDueDate}`);
        await supabase
            .from('reminders')
            .update({ first_due_date: newDueDate })
            .eq('id', rem.id);

        // Update notifications for this reminder
        const { data: notifs } = await supabase
            .from('notifications')
            .select('*')
            .eq('reminder_id', rem.id);

        for (const notif of (notifs || [])) {
            const notifDueDate = (notif.current_due_date || '').replace('2027-', '2026-');
            const notifSendDate = (notif.scheduled_send_date || '').replace('2027-', '2026-');
            console.log(`Updating notification ${notif.id} current_due_date: ${notifDueDate}, scheduled_send_date: ${notifSendDate}`);
            await supabase
                .from('notifications')
                .update({ current_due_date: notifDueDate, scheduled_send_date: notifSendDate })
                .eq('id', notif.id);
        }
    }

    console.log('Finished updating Supabase records!');
}

fixDates()
    .then(() => process.exit(0))
    .catch(err => {
        console.error(err);
        process.exit(1);
    });
