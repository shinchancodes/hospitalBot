import os
import psycopg2
import psycopg2.extras
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────────
DB_URL         = os.environ["DATABASE_URL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]

st.set_page_config(
    page_title="Hospital Admin",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Auth ──────────────────────────────────────────────────────────
def check_password():
    if st.session_state.get("authenticated"):
        return
    st.title("🏥 Hospital Admin Panel")
    st.subheader("Login")
    pwd = st.text_input("Password", type="password")
    if st.button("Login", use_container_width=True):
        if pwd == ADMIN_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("❌ Incorrect password")
    st.stop()

check_password()

# ── DB helpers ────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        DB_URL,
        sslmode="require",
        connect_timeout=10,
        cursor_factory=psycopg2.extras.RealDictCursor
    )

def run_query(sql: str, params=None) -> pd.DataFrame:
    conn = get_conn()
    try:
        df = pd.read_sql(sql, conn, params=params)
        return df
    finally:
        conn.close()

def run_write(sql: str, params=None):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()

def clear_cache():
    st.cache_data.clear()

# ── DEBUG: Test database connection ───────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Debug Info")
try:
    test_conn = get_conn()
    test_cur = test_conn.cursor()
    test_cur.execute("SELECT COUNT(*) as count FROM patients")
    patient_count = test_cur.fetchone()["count"]
    test_conn.close()
    st.sidebar.success(f"✅ DB Connected")
    st.sidebar.text(f"Patients in DB: {patient_count}")
except Exception as e:
    st.sidebar.error(f"❌ DB Error: {e}")
# ──────────────────────────────────────────────────────────────────

# ── Data loaders ──────────────────────────────────────────────────
@st.cache_data(ttl=20)
def load_patients():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, telegram_id, full_name, phone, date_of_birth, 
                   notes, is_active, created_at 
            FROM patients 
            ORDER BY created_at DESC
        """)
        rows = cur.fetchall()
        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(columns=['id', 'telegram_id', 'full_name', 'phone', 'date_of_birth', 'notes', 'is_active', 'created_at'])
        return df
    finally:
        conn.close()

@st.cache_data(ttl=20)
def load_appointments():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                a.id, p.full_name AS patient, p.phone,
                a.doctor,
                a.appointment_date, a.status, a.notes,
                a.created_at
            FROM appointments a
            JOIN patients p ON p.id = a.patient_id
            ORDER BY a.appointment_date DESC
        """)
        rows = cur.fetchall()
        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(columns=['id', 'patient', 'phone', 'doctor', 'appointment_date', 'status', 'notes', 'created_at'])
        return df
    finally:
        conn.close()

@st.cache_data(ttl=20)
def load_doctors():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, specialty, is_active, created_at 
            FROM doctors 
            ORDER BY name ASC
        """)
        rows = cur.fetchall()
        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(columns=['id', 'name', 'specialty', 'is_active', 'created_at'])
        return df
    finally:
        conn.close()

@st.cache_data(ttl=20)
def load_slots():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT ds.id, d.name AS doctor, ds.slot_time, ds.is_active
            FROM doctor_slots ds
            JOIN doctors d ON d.id = ds.doctor_id
            ORDER BY ds.slot_time ASC
        """)
        rows = cur.fetchall()
        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(columns=['id', 'doctor', 'slot_time', 'is_active'])
        return df
    finally:
        conn.close()

@st.cache_data(ttl=20)
def load_doctors_for_slots():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name 
            FROM doctors 
            WHERE is_active = TRUE 
            ORDER BY name
        """)
        rows = cur.fetchall()
        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(columns=['id', 'name'])
        return df
    finally:
        conn.close()

# ── Sidebar ───────────────────────────────────────────────────────
st.sidebar.title("🏥 Hospital Admin")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Navigate",
    ["📊 Dashboard", "👥 Patients", "📅 Appointments", "➕ Add Appointment", "👨‍⚕️ Doctors", "🕐 Slots"],
)
st.sidebar.markdown("---")
if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
    clear_cache()
    st.rerun()
if st.sidebar.button("🚪 Logout", use_container_width=True):
    st.session_state.authenticated = False
    st.rerun()

# ══════════════════════════════════════════════════════════════════
# ── DASHBOARD ─────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
if page == "📊 Dashboard":
    if st.button("Force Refresh"):
        clear_cache()
        st.rerun()
    st.title("📊 Dashboard")

    patients     = load_patients()
    appointments = load_appointments()
    doctors      = load_doctors()
    slots        = load_slots()

    print(patients)

    # KPI row
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Patients",      len(patients))
    c2.metric("Total Appointments",  len(appointments))
    scheduled  = appointments[appointments["status"] == "scheduled"]
    print("DEBUG: Appointments DataFrame:", scheduled.head())

    completed  = appointments[appointments["status"] == "completed"]
    cancelled  = appointments[appointments["status"] == "cancelled"]
    c3.metric("Scheduled",  len(scheduled))
    c4.metric("Completed",  len(completed))
    c5.metric("Cancelled",  len(cancelled))

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📅 Next 10 Upcoming Appointments")
        if not scheduled.empty:
            upcoming = (
                scheduled.sort_values("appointment_date")
                .head(10)[["patient", "doctor", "appointment_date", "notes"]]
            )
            st.dataframe(upcoming, use_container_width=True, hide_index=True)
        else:
            st.info("No upcoming appointments.")

    with col2:
        st.subheader("🆕 Recently Registered Patients")
        recent = patients.head(10)[["full_name", "phone", "is_active", "created_at"]]
        st.dataframe(recent, use_container_width=True, hide_index=True)

    st.markdown("---")

    col3, col4 = st.columns(2)

    with col3:
        st.subheader("📈 Appointments by Status")
        status_counts = appointments["status"].value_counts().reset_index()
        status_counts.columns = ["Status", "Count"]
        st.bar_chart(status_counts.set_index("Status"))

    with col4:
        st.subheader("👨‍⚕️ Active Doctors")
        active_doctors = doctors[doctors["is_active"] == True]
        st.metric("Active Doctors", len(active_doctors))
        st.dataframe(
            active_doctors[["name", "specialty"]],
            use_container_width=True,
            hide_index=True
        )

# ══════════════════════════════════════════════════════════════════
# ── PATIENTS ──────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
elif page == "👥 Patients":
    st.title("👥 Patient Management")

    patients = load_patients()

    # Search
    search = st.text_input("🔍 Search by name or phone")
    if search:
        mask = (
            patients["full_name"].str.contains(search, case=False, na=False) |
            patients["phone"].astype(str).str.contains(search, case=False, na=False)
        )
        patients = patients[mask]

    # Filter active
    show_inactive = st.checkbox("Show inactive patients", value=False)
    if not show_inactive:
        patients = patients[patients["is_active"] == True]

    st.dataframe(patients, use_container_width=True, hide_index=True)
    st.caption(f"Showing {len(patients)} patient(s)")

    st.markdown("---")
    st.subheader("✏️ Edit Patient")

    all_patients = load_patients()
    options = {f"[{r['id']}] {r['full_name']}": r["id"] for _, r in all_patients.iterrows()}
    selected = st.selectbox("Select patient", list(options.keys()))

    if selected:
        pid = options[selected]
        row = all_patients[all_patients["id"] == pid].iloc[0]

        with st.form("edit_patient"):
            new_name   = st.text_input("Full Name",       value=row["full_name"])
            new_phone  = st.text_input("Phone",           value=row["phone"] or "")
            new_notes  = st.text_area("Notes",            value=row["notes"] or "")
            new_active = st.checkbox("Active",            value=bool(row["is_active"]))
            col1, col2 = st.columns(2)
            save   = col1.form_submit_button("💾 Save Changes", use_container_width=True)
            delete = col2.form_submit_button("🗑️ Delete Patient", use_container_width=True, type="secondary")

        if save:
            run_write(
                "UPDATE patients SET full_name=%s, phone=%s, notes=%s, is_active=%s WHERE id=%s",
                (new_name, new_phone or None, new_notes or None, new_active, pid),
            )
            clear_cache()
            st.success("✅ Patient updated!")
            st.rerun()

        if delete:
            run_write("DELETE FROM patients WHERE id=%s", (pid,))
            clear_cache()
            st.success("🗑️ Patient deleted.")
            st.rerun()

# ══════════════════════════════════════════════════════════════════
# ── APPOINTMENTS ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
elif page == "📅 Appointments":
    st.title("📅 Appointment Management")

    appointments = load_appointments()

    # Filters
    col1, col2, col3 = st.columns(3)
    status_filter = col1.selectbox("Status", ["all", "scheduled", "completed", "cancelled"])
    search_doc    = col2.text_input("🔍 Search doctor")
    search_pat    = col3.text_input("🔍 Search patient")

    filtered = appointments.copy()
    if status_filter != "all":
        filtered = filtered[filtered["status"] == status_filter]
    if search_doc:
        filtered = filtered[filtered["doctor"].str.contains(search_doc, case=False, na=False)]
    if search_pat:
        filtered = filtered[filtered["patient"].str.contains(search_pat, case=False, na=False)]

    st.dataframe(filtered, use_container_width=True, hide_index=True)
    st.caption(f"Showing {len(filtered)} appointment(s)")

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("✏️ Update Status")
        appt_id    = st.number_input("Appointment ID", min_value=1, step=1, key="upd_id")
        new_status = st.selectbox("New Status", ["scheduled", "completed", "cancelled"])
        new_notes  = st.text_area("Update Notes (optional)", key="upd_notes")
        if st.button("✅ Update", use_container_width=True):
            if new_notes:
                run_write(
                    "UPDATE appointments SET status=%s, notes=%s WHERE id=%s",
                    (new_status, new_notes, int(appt_id)),
                )
            else:
                run_write(
                    "UPDATE appointments SET status=%s WHERE id=%s",
                    (new_status, int(appt_id)),
                )
            clear_cache()
            st.success(f"Appointment {appt_id} → {new_status}")
            st.rerun()

    with col2:
        st.subheader("🗑️ Delete Appointment")
        del_id = st.number_input("Appointment ID to delete", min_value=1, step=1, key="del_id")
        st.warning("⚠️ This action cannot be undone.")
        if st.button("🗑️ Delete Appointment", use_container_width=True, type="secondary"):
            run_write("DELETE FROM appointments WHERE id=%s", (int(del_id),))
            clear_cache()
            st.success(f"Appointment {del_id} deleted.")
            st.rerun()

# ══════════════════════════════════════════════════════════════════
# ── ADD APPOINTMENT ───────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
elif page == "➕ Add Appointment":
    st.title("➕ Add Appointment (Admin)")

    all_patients = load_patients()
    all_doctors  = load_doctors()
    patient_opts = {f"[{r['id']}] {r['full_name']}": r["id"] for _, r in all_patients.iterrows()}
    doctor_opts  = list(all_doctors[all_doctors["is_active"] == True]["name"])

    with st.form("add_appt"):
        selected_pat = st.selectbox("Patient", list(patient_opts.keys()))
        doctor       = st.selectbox("Doctor", doctor_opts)
        appt_date    = st.date_input("Appointment Date")
        appt_time    = st.time_input("Appointment Time")
        notes        = st.text_area("Notes (optional)")
        submitted    = st.form_submit_button("📅 Book Appointment", use_container_width=True)

    if submitted:
        if not doctor:
            st.error("Doctor is required.")
        else:
            dt         = datetime.combine(appt_date, appt_time)
            patient_id = patient_opts[selected_pat]
            try:
                run_write(
                    """
                    INSERT INTO appointments (patient_id, doctor, appointment_date, notes)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (patient_id, doctor, dt, notes or None),
                )
                clear_cache()
                st.success(f"✅ Appointment booked for {selected_pat} with {doctor} on {dt.strftime('%b %d, %Y at %H:%M')}")
            except Exception as e:
                if "no_double_booking" in str(e):
                    st.error("⚠️ That time slot is already booked for this doctor.")
                else:
                    st.error(f"Error: {e}")

# ══════════════════════════════════════════════════════════════════
# ── DOCTORS ───────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
elif page == "👨‍⚕️ Doctors":
    st.title("👨‍⚕️ Doctor Management")

    doctors = load_doctors()

    # Show active/inactive toggle
    show_inactive = st.checkbox("Show inactive doctors", value=False)
    display = doctors if show_inactive else doctors[doctors["is_active"] == True]
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.caption(f"Showing {len(display)} doctor(s)")

    st.markdown("---")
    col1, col2 = st.columns(2)

    # Add new doctor
    with col1:
        st.subheader("➕ Add Doctor")
        with st.form("add_doctor"):
            new_name      = st.text_input("Doctor Name")
            new_specialty = st.text_input("Specialty (optional)")
            submitted     = st.form_submit_button("Add Doctor", use_container_width=True)
        if submitted:
            if not new_name:
                st.error("Name is required.")
            else:
                try:
                    run_write(
                        "INSERT INTO doctors (name, specialty) VALUES (%s, %s)",
                        (new_name.strip(), new_specialty.strip() or None),
                    )
                    clear_cache()
                    st.success(f"✅ {new_name} added!")
                    st.rerun()
                except Exception as e:
                    if "unique" in str(e).lower():
                        st.error("A doctor with that name already exists.")
                    else:
                        st.error(f"Error: {e}")

    # Edit / deactivate existing doctor
    with col2:
        st.subheader("✏️ Edit Doctor")
        options = {f"[{r['id']}] {r['name']}": r["id"] for _, r in doctors.iterrows()}
        selected = st.selectbox("Select doctor", list(options.keys()))
        if selected:
            did = options[selected]
            row = doctors[doctors["id"] == did].iloc[0]
            with st.form("edit_doctor"):
                upd_name      = st.text_input("Name",      value=row["name"])
                upd_specialty = st.text_input("Specialty", value=row["specialty"] or "")
                upd_active    = st.checkbox("Active",      value=bool(row["is_active"]))
                col_a, col_b  = st.columns(2)
                save   = col_a.form_submit_button("💾 Save",   use_container_width=True)
                delete = col_b.form_submit_button("🗑️ Delete", use_container_width=True, type="secondary")
            if save:
                run_write(
                    "UPDATE doctors SET name=%s, specialty=%s, is_active=%s WHERE id=%s",
                    (upd_name, upd_specialty or None, upd_active, did),
                )
                clear_cache()
                st.success("✅ Doctor updated!")
                st.rerun()
            if delete:
                run_write("DELETE FROM doctors WHERE id=%s", (did,))
                clear_cache()
                st.success("🗑️ Doctor deleted.")
                st.rerun()

# ══════════════════════════════════════════════════════════════════
# ── SLOTS ─────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
elif page == "🕐 Slots":
    st.title("🕐 Slot Management")

    slots   = load_slots()
    doctors = load_doctors_for_slots()

    # ── View slots ────────────────────────────────────────────────
    st.subheader("📋 All Slots")
    doctor_filter = st.selectbox(
        "Filter by doctor",
        ["All"] + list(doctors["name"]),
        key="slot_filter"
    )
    show_inactive = st.checkbox("Show inactive slots", value=False)

    filtered = slots.copy()
    if doctor_filter != "All":
        filtered = filtered[filtered["doctor"] == doctor_filter]
    if not show_inactive:
        filtered = filtered[filtered["is_active"] == True]

    st.dataframe(filtered, use_container_width=True, hide_index=True)
    st.caption(f"Showing {len(filtered)} slot(s)")

    st.markdown("---")

    col1, col2 = st.columns(2)

    # ── Add single slot ───────────────────────────────────────────
    with col1:
        st.subheader("➕ Add Single Slot")
        with st.form("add_slot"):
            doc_options = {r["name"]: r["id"] for _, r in doctors.iterrows()}
            sel_doc  = st.selectbox("Doctor", list(doc_options.keys()))
            sel_date = st.date_input("Date")
            sel_time = st.time_input("Time")
            submitted = st.form_submit_button("Add Slot", use_container_width=True)
        if submitted:
            slot_dt = datetime.combine(sel_date, sel_time)
            try:
                run_write(
                    "INSERT INTO doctor_slots (doctor_id, slot_time) VALUES (%s, %s)",
                    (doc_options[sel_doc], slot_dt),
                )
                clear_cache()
                st.success(f"✅ Slot added for {sel_doc} on {slot_dt.strftime('%b %d at %H:%M')}")
                st.rerun()
            except Exception as e:
                if "unique" in str(e).lower():
                    st.error("That slot already exists for this doctor.")
                else:
                    st.error(f"Error: {e}")

    # ── Bulk add slots ────────────────────────────────────────────
    with col2:
        st.subheader("⚡ Bulk Add Slots")
        st.caption("Generate recurring slots for a doctor automatically.")
        with st.form("bulk_slots"):
            doc_options2  = {r["name"]: r["id"] for _, r in doctors.iterrows()}
            bulk_doc      = st.selectbox("Doctor", list(doc_options2.keys()), key="bulk_doc")
            bulk_date     = st.date_input("Start Date", key="bulk_date")
            bulk_days     = st.number_input("Number of days", min_value=1, max_value=30, value=7)
            start_time    = st.time_input("First slot time", key="bulk_start")
            end_time      = st.time_input("Last slot time",  key="bulk_end")
            interval_mins = st.selectbox("Slot interval (minutes)", [15, 20, 30, 45, 60], index=2)
            submitted2    = st.form_submit_button("Generate Slots", use_container_width=True)

        if submitted2:
            doctor_id  = doc_options2[bulk_doc]
            added      = 0
            skipped    = 0

            for day_offset in range(bulk_days):
                current_day = bulk_date + timedelta(days=day_offset)
                slot_dt     = datetime.combine(current_day, start_time)
                end_dt      = datetime.combine(current_day, end_time)

                while slot_dt <= end_dt:
                    try:
                        run_write(
                            "INSERT INTO doctor_slots (doctor_id, slot_time) VALUES (%s, %s)",
                            (doctor_id, slot_dt),
                        )
                        added += 1
                    except Exception:
                        skipped += 1
                    slot_dt += timedelta(minutes=interval_mins)

            clear_cache()
            st.success(f"✅ Done! {added} slots added, {skipped} skipped (already existed).")
            st.rerun()

    st.markdown("---")

    # ── Deactivate / delete slot ──────────────────────────────────
    st.subheader("✏️ Edit Slot")
    slot_id    = st.number_input("Slot ID", min_value=1, step=1)
    col_a, col_b, col_c = st.columns(3)
    if col_a.button("✅ Activate",   use_container_width=True):
        run_write("UPDATE doctor_slots SET is_active=TRUE  WHERE id=%s", (int(slot_id),))
        clear_cache()
        st.success("Slot activated!")
        st.rerun()
    if col_b.button("⏸ Deactivate", use_container_width=True):
        run_write("UPDATE doctor_slots SET is_active=FALSE WHERE id=%s", (int(slot_id),))
        clear_cache()
        st.success("Slot deactivated!")
        st.rerun()
    if col_c.button("🗑️ Delete",     use_container_width=True, type="secondary"):
        run_write("DELETE FROM doctor_slots WHERE id=%s", (int(slot_id),))
        clear_cache()
        st.success("Slot deleted!")
        st.rerun()