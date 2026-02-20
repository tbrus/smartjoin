# Dataset 03: health_composite_codes
Expected joins:
- visits.patient_id -> patients.patient_id (dirty keys)
- diagnoses.visit_id -> visits.visit_id
- diagnoses.icd10_code -> icd10_dim.icd10_code
Composite key:
- diagnoses(visit_id, seq) near-unique
Traps:
- country, status, present_on_admission, created_date
