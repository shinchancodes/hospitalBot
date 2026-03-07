-- Migration: Prevent double-booking of appointment slots
-- Adds a unique constraint to ensure only one appointment per doctor per time slot

-- Add unique constraint on (doctor, appointment_date) for scheduled appointments
ALTER TABLE appointments 
ADD CONSTRAINT unique_doctor_appointment_slot 
UNIQUE (doctor, appointment_date) 
WHERE status = 'scheduled';
