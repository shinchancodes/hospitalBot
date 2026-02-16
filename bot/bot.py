import os
import psycopg2
import psycopg2.extras
import psycopg2.errors
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, ConversationHandler,
    MessageHandler, ContextTypes, filters
)

# ── Config ────────────────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
DB_URL    = os.environ["DATABASE_URL"]

# ── Menu button labels ────────────────────────────────────────────
BTN_BOOK    = "📅 Book Appointment"
BTN_LIST    = "📋 My Appointments"
BTN_PROFILE = "👤 Update Profile"
BTN_CANCEL  = "❌ Cancel"

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_BOOK),    KeyboardButton(BTN_LIST)],
        [KeyboardButton(BTN_PROFILE), KeyboardButton(BTN_CANCEL)],
    ],
    resize_keyboard=True,
    input_field_placeholder="Choose an option or type a message...",
)

# ── Conversation states ───────────────────────────────────────────
(APPT_DOCTOR, APPT_DATE, APPT_NOTES) = range(3)
(PROF_NAME, PROF_PHONE, PROF_DOB)    = range(3, 6)

# ── DB helpers ────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        DB_URL,
        sslmode="require",
        cursor_factory=psycopg2.extras.RealDictCursor
    )

def get_or_create_patient(telegram_id: int, full_name: str) -> int:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM patients WHERE telegram_id = %s", (telegram_id,))
        row = cur.fetchone()
        if row:
            return row["id"]
        cur.execute(
            "INSERT INTO patients (telegram_id, full_name) VALUES (%s, %s) RETURNING id",
            (telegram_id, full_name),
        )
        patient_id = cur.fetchone()["id"]
        conn.commit()
        return patient_id
    finally:
        conn.close()

def get_booked_slots(doctor: str) -> list:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT appointment_date FROM appointments
            WHERE doctor = %s
              AND status = 'scheduled'
              AND appointment_date > NOW()
            ORDER BY appointment_date ASC
            """,
            (doctor,),
        )
        return [row["appointment_date"].strftime("%b %d %Y %H:%M") for row in cur.fetchall()]
    finally:
        conn.close()

def parse_date(text: str):
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    return None

# ── Helper: send main menu ────────────────────────────────────────
async def send_menu(update: Update, text: str):
    await update.message.reply_text(text, reply_markup=MAIN_MENU)

# ── /start ────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_patient(user.id, user.full_name)
    await send_menu(
        update,
        f"👋 Hello {user.first_name}! Welcome to the Hospital Appointment Bot.\n\n"
        "Use the menu below to get started:"
    )

# ── Cancel (works during conversations AND from menu button) ──────
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await send_menu(update, "❌ Action cancelled.")
    return ConversationHandler.END

# ── My Appointments ───────────────────────────────────────────────
async def my_appointments(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.doctor, a.appointment_date, a.status, a.notes
            FROM appointments a
            JOIN patients p ON p.id = a.patient_id
            WHERE p.telegram_id = %s
            ORDER BY a.appointment_date ASC
            """,
            (user.id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        await send_menu(update, "You have no appointments yet. Tap 📅 Book Appointment to add one.")
        return

    upcoming = [r for r in rows if r["status"] == "scheduled"]
    past     = [r for r in rows if r["status"] != "scheduled"]

    msg = "📋 *Your Appointments*\n\n"
    if upcoming:
        msg += "*📅 Upcoming:*\n"
        for r in upcoming:
            msg += (
                f"  🩺 Dr. {r['doctor']}\n"
                f"  📅 {r['appointment_date'].strftime('%b %d, %Y at %H:%M')}\n"
                f"  📝 {r['notes'] or 'No notes'}\n\n"
            )
    if past:
        msg += "*📁 Past:*\n"
        for r in past:
            emoji = "✅" if r["status"] == "completed" else "❌"
            msg += (
                f"  {emoji} Dr. {r['doctor']} — {r['hospital']}\n"
                f"  📅 {r['appointment_date'].strftime('%b %d, %Y at %H:%M')}\n\n"
            )

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=MAIN_MENU)

# ── Book Appointment conversation ─────────────────────────────────
async def book_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🩺 *Step 1 of 4* — Which doctor would you like to see?\n\nType the doctor's name:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton(BTN_CANCEL)]],
            resize_keyboard=True,
        ),
    )
    return APPT_DOCTOR

async def book_doctor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == BTN_CANCEL:
        return await cancel(update, ctx)
    ctx.user_data["doctor"] = update.message.text.strip()
    await update.message.reply_text(
        "📅 *Step 2 of 3* — Enter your preferred date and time:\n"
        "Format: `YYYY-MM-DD HH:MM`  e.g. `2025-03-20 14:30`",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton(BTN_CANCEL)]],
            resize_keyboard=True,
        ),
    )
    return APPT_DATE

async def book_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == BTN_CANCEL:
        return await cancel(update, ctx)
    dt = parse_date(update.message.text)
    if not dt:
        await update.message.reply_text(
            "❌ Couldn't read that date. Please use:\n`YYYY-MM-DD HH:MM`  e.g. `2025-03-20 14:30`",
            parse_mode="Markdown",
        )
        return APPT_DATE
    if dt < datetime.now():
        await update.message.reply_text("⚠️ That date is in the past. Please enter a future date:")
        return APPT_DATE

    ctx.user_data["date"] = dt
    await update.message.reply_text(
        "📝 *Step 3 of 3* — Any notes? (type `none` to skip)",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("none")], [KeyboardButton(BTN_CANCEL)]],
            resize_keyboard=True,
        ),
    )
    return APPT_NOTES

async def book_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == BTN_CANCEL:
        return await cancel(update, ctx)
    notes      = update.message.text.strip()
    notes      = None if notes.lower() == "none" else notes
    user       = update.effective_user
    patient_id = get_or_create_patient(user.id, user.full_name)
    d          = ctx.user_data

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO appointments (patient_id, doctor, appointment_date, notes)
            VALUES (%s, %s, %s, %s)
            """,
            (patient_id, d["doctor"], d["date"], notes),
        )
        conn.commit()
        await update.message.reply_text(
            f"✅ *Appointment Booked!*\n\n"
            f"🩺 Dr. {d['doctor']}\n"
            f"📅 {d['date'].strftime('%B %d, %Y at %H:%M')}\n"
            f"📝 {notes or 'No notes'}\n\n"
            "Use 📋 My Appointments to view all your bookings.",
            parse_mode="Markdown",
            reply_markup=MAIN_MENU,
        )
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        await send_menu(
            update,
            "⚠️ That time slot is already taken for this doctor.\n"
            "Please tap 📅 Book Appointment and choose a different time."
        )
    except Exception as e:
        conn.rollback()
        await send_menu(update, f"❌ Something went wrong: {e}")
    finally:
        conn.close()

    ctx.user_data.clear()
    return ConversationHandler.END

# ── Update Profile conversation ───────────────────────────────────
async def profile_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👤 *Step 1 of 3* — Enter your full name:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton(BTN_CANCEL)]],
            resize_keyboard=True,
        ),
    )
    return PROF_NAME

async def profile_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == BTN_CANCEL:
        return await cancel(update, ctx)
    ctx.user_data["full_name"] = update.message.text.strip()
    await update.message.reply_text(
        "📱 *Step 2 of 3* — Enter your phone number:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton(BTN_CANCEL)]],
            resize_keyboard=True,
        ),
    )
    return PROF_PHONE

async def profile_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == BTN_CANCEL:
        return await cancel(update, ctx)
    ctx.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text(
        "🎂 *Step 3 of 3* — Date of birth:\nFormat: `YYYY-MM-DD`  e.g. `1990-05-15`",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton(BTN_CANCEL)]],
            resize_keyboard=True,
        ),
    )
    return PROF_DOB

async def profile_dob(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == BTN_CANCEL:
        return await cancel(update, ctx)
    try:
        dob = datetime.strptime(update.message.text.strip(), "%Y-%m-%d").date()
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid format. Use `YYYY-MM-DD` e.g. `1990-05-15`",
            parse_mode="Markdown",
        )
        return PROF_DOB

    user = update.effective_user
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE patients SET full_name=%s, phone=%s, date_of_birth=%s WHERE telegram_id=%s",
            (ctx.user_data["full_name"], ctx.user_data["phone"], dob, user.id),
        )
        conn.commit()
    finally:
        conn.close()

    ctx.user_data.clear()
    await send_menu(update, "✅ Profile updated successfully!")
    return ConversationHandler.END

# ── Main ──────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Filter for each menu button text
    btn_book    = filters.Text([BTN_BOOK])
    btn_list    = filters.Text([BTN_LIST])
    btn_profile = filters.Text([BTN_PROFILE])
    btn_cancel  = filters.Text([BTN_CANCEL])

    # Book conversation
    book_conv = ConversationHandler(
        entry_points=[
            CommandHandler("book", book_start),
            MessageHandler(btn_book, book_start),
        ],
        states={
            APPT_DOCTOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, book_doctor)],
            APPT_DATE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, book_date)],
            APPT_NOTES:  [MessageHandler(filters.TEXT & ~filters.COMMAND, book_notes)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(btn_cancel, cancel),
        ],
        allow_reentry=True,
    )

    # Profile conversation
    profile_conv = ConversationHandler(
        entry_points=[
            CommandHandler("updateprofile", profile_start),
            MessageHandler(btn_profile, profile_start),
        ],
        states={
            PROF_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_name)],
            PROF_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_phone)],
            PROF_DOB:   [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_dob)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(btn_cancel, cancel),
        ],
        allow_reentry=True,
    )

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(btn_list, my_appointments))
    app.add_handler(MessageHandler(btn_cancel, cancel))
    app.add_handler(book_conv)
    app.add_handler(profile_conv)

    print("🤖 Bot running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()