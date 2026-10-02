const { getDb } = require('./db.js');

async function updateGolfBallDate() {
    const db = await getDb();
    
    const client = await db.get(`SELECT * FROM clients WHERE id = 20`);
    if (!client) {
        console.log('Client not found');
        return;
    }
    
    console.log('Targeting client:', client.name, client.id);
    
    // Update reminder schedule start_due_date to 2026-09-30
    await db.run(
        `UPDATE reminders SET start_due_date = '2026-09-30' WHERE client_id = 20 AND reminder_type_id = 4`
    );
    
    // Update pending notification due_date & send_date to 2026-09-30
    await db.run(
        `UPDATE notifications SET due_date = '2026-09-30', send_date = '2026-08-01' WHERE id = 36`
    );
    
    const updatedNotif = await db.get(`SELECT * FROM notifications WHERE id = 36`);
    console.log('Updated Notification 36:', updatedNotif);
}

updateGolfBallDate()
    .then(() => process.exit(0))
    .catch(err => {
        console.error(err);
        process.exit(1);
    });
