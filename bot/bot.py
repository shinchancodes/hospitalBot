import os
import psycopg2
import psycopg2.extras        # ← add this line
import psycopg2.errors        # ← add this line too (used later in the code)
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ConversationHandler,
    MessageHandler, ContextTypes, filters
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
DB_URL = os.environ["DATABASE_URL"]

# Conversation states
PATIENT_NAME, PATIENT_PHONE, PATIENT_DOB = range(3)
APPT_DOCTOR, APPT_HOSPITAL, APPT_DATE, APPT_NOTES = range(3, 7)

def db():
    return psycopg2.connect(DB_URL)

def get_conn():
    return psycopg2.connect(
        DB_URL,
        sslmode="require",
        cursor_factory=psycopg2.extras.RealDictCursor
    )

def get_or_create_patient(telegram_id, full_name):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM patients WHERE telegram_id = %s", (telegram_id,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row['id']
    cur.execute(
        "INSERT INTO patients (telegram_id, full_name) VALUES (%s, %s) RETURNING id",
        (telegram_id, full_name)
    )
    patient_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return patient_id

# /start
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    print(f"User {update.effective_user.id} started the bot.")
    user = update.effective_user
    get_or_create_patient(user.id, user.full_name)
    await update.message.reply_text(
        f"👋 Hello {user.first_name}!\n\n"
        "I can help you manage hospital appointments.\n\n"
        "/book — Book a new appointment\n"
        "/myappointments — View your appointments\n"
        "/updateprofile — Update your details\n"
        "/cancel — Cancel current action"
    )

# /book flow
async def book(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🩺 Which doctor are you seeing?")
    return APPT_DOCTOR

async def appt_doctor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["doctor"] = update.message.text
    await update.message.reply_text("🏥 Which hospital?")
    return APPT_HOSPITAL

async def appt_hospital(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["hospital"] = update.message.text
    await update.message.reply_text("📅 Date and time? (e.g. 2025-03-20 14:30)")
    return APPT_DATE

async def appt_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["date"] = update.message.text
    await update.message.reply_text("📝 Any notes? (or type 'none')")
    return APPT_NOTES

async def appt_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    notes = update.message.text
    if notes.lower() == "none":
        notes = None
    user = update.effective_user
    patient_id = get_or_create_patient(user.id, user.full_name)
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO appointments (patient_id, doctor, hospital, appointment_date, notes)
            VALUES (%s, %s, %s, %s, %s)
        """, (patient_id, ctx.user_data["doctor"], ctx.user_data["hospital"],
              ctx.user_data["date"], notes))
        conn.commit()
        conn.close()
        await update.message.reply_text("✅ Appointment booked! Use /myappointments to view it.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
    return ConversationHandler.END

# /myappointments
async def my_appointments(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.doctor, a.hospital, a.appointment_date, a.status, a.notes
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE p.telegram_id = %s
        ORDER BY a.appointment_date ASC
    """, (user.id,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No appointments yet. Use /book to add one.")
        return
    msg = "📋 *Your Appointments:*\n\n"
    for r in rows:
        msg += (f"🩺 Dr. {r[0]} at {r[1]}\n"
                f"📅 {r[2].strftime('%b %d, %Y %H:%M')}\n"
                f"Status: {r[3].upper()}\n"
                f"📝 {r[4] or 'No notes'}\n\n")
    await update.message.reply_text(msg, parse_mode="Markdown")

# /updateprofile flow
async def update_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 Enter your full name:")
    return PATIENT_NAME

async def profile_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["full_name"] = update.message.text
    await update.message.reply_text("📱 Enter your phone number:")
    return PATIENT_PHONE

async def profile_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["phone"] = update.message.text
    await update.message.reply_text("🎂 Date of birth? (e.g. 1990-05-15)")
    return PATIENT_DOB

async def profile_dob(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE patients SET full_name=%s, phone=%s, date_of_birth=%s
        WHERE telegram_id=%s
    """, (ctx.user_data["full_name"], ctx.user_data["phone"],
          update.message.text, user.id))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Profile updated!")
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    book_conv = ConversationHandler(
        entry_points=[CommandHandler("book", book)],
        states={
            APPT_DOCTOR:  [MessageHandler(filters.TEXT & ~filters.COMMAND, appt_doctor)],
            APPT_HOSPITAL:[MessageHandler(filters.TEXT & ~filters.COMMAND, appt_hospital)],
            APPT_DATE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, appt_date)],
            APPT_NOTES:   [MessageHandler(filters.TEXT & ~filters.COMMAND, appt_notes)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    profile_conv = ConversationHandler(
        entry_points=[CommandHandler("updateprofile", update_profile)],
        states={
            PATIENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_name)],
            PATIENT_PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND, profile_phone)],
            PATIENT_DOB:  [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_dob)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myappointments", my_appointments))
    app.add_handler(book_conv)
    app.add_handler(profile_conv)

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()