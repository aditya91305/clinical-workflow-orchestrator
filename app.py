import json
import urllib.request
import re
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# Connection string using local loopback IP and default Postgres port
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://adityanag@127.0.0.1:5432/clinical_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
PATIENT_ID_REGEX = re.compile(r"^PT-\d{4,6}$")
TRIAL_ID_REGEX = re.compile(r"^CT-\d{4}-[A-Z]{2,4}$")
VALID_STATUSES = {"PENDING", "APPROVED", "REJECTED", "COMPLETED"}

def validate_clinical_payload(data):
    """
    Validates payload integrity and structure.
    Returns: (is_valid: bool, error_message: str | None)
    """
    if not isinstance(data, dict):
        return False, "Payload must be a valid JSON object."
    
    trial_id = data.get("trial_id")
    patient_id = data.get("patient_id")
    findings = data.get("findings")
    status = data.get("status", "PENDING").strip().upper()

    # Required field presence
    if not trial_id or not patient_id or not findings:
        return False, "Fields 'trial_id', 'patient_id', and 'findings' are mandatory."
    if not PATIENT_ID_REGEX.match(patient_id.strip()):
        return False, "Invalid 'patient_id' format. Expected: PT-XXXX or PT-XXXXXX."
    if not TRIAL_ID_REGEX.match(trial_id.strip()):
        return False, "Invalid 'trial_id' format. Expected: CT-YYYY-DEPT."
    if status not in VALID_STATUSES:
        return False, f"Invalid status '{status}'. Permitted values: {', '.join(sorted(VALID_STATUSES))}."
    if len(findings.strip()) < 10:
        return False, "Field 'findings' must contain at least 10 characters."
        
    return True, None


# Relational model representing clinical reports
class ClinicalReport(db.Model):
    __tablename__ = 'clinical_reports'

    id = db.Column(db.Integer, primary_key=True)
    trial_id = db.Column(db.String(50), nullable=False, index=True)
    patient_id = db.Column(db.String(50), nullable=False, index=True)
    status = db.Column(db.String(30), default='PENDING')
    findings = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        """Serializes SQL row attributes into a Python dictionary."""
        return {
            "id": self.id,
            "trial_id": self.trial_id,
            "patient_id": self.patient_id,
            "status": self.status,
            "findings": self.findings,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


# Root route - serves the UI Dashboard
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/simulate-ingest', methods=['POST'])
def simulate_ingest():
    data = request.get_json() or {}
    
    # Direct loopback request to n8n webhook listener
    n8n_url = "http://127.0.0.1:5678/webhook-test/clinical-report-ingest"
    req = urllib.request.Request(
        n8n_url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_body = response.read().decode('utf-8')
            return jsonify({"status": "forwarded", "response": res_body}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to reach n8n: {str(e)}"}), 502


# Health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "Enterprise Clinical Workflow Orchestrator"
    }), 200


# Create report endpoint with validation and error handling
@app.route('/api/reports', methods=['POST'])
def create_report():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Missing JSON request body"}), 400

    # 1. Execute custom business logic validation
    is_valid, error_msg = validate_clinical_payload(data)
    if not is_valid:
        return jsonify({"error": "Validation failed", "details": error_msg}), 422

    t_id = data['trial_id'].strip()
    p_id = data['patient_id'].strip()
    status_val = data.get('status', 'PENDING').strip().upper()
    findings_val = data['findings'].strip()

    # 2. Check if a report for this patient in this trial already exists
    existing_report = ClinicalReport.query.filter_by(
        trial_id=t_id, 
        patient_id=p_id
    ).first()

    try:
        if existing_report:
            # UPDATE existing record
            existing_report.status = status_val
            existing_report.findings = findings_val
            db.session.commit()
            return jsonify({
                "message": "Report updated successfully (Upsert)",
                "data": existing_report.to_dict()
            }), 200
        else:
            # INSERT new record
            new_report = ClinicalReport(
                trial_id=t_id,
                patient_id=p_id,
                findings=findings_val,
                status=status_val
            )
            db.session.add(new_report)
            db.session.commit()
            return jsonify({
                "message": "Report created successfully",
                "data": new_report.to_dict()
            }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Database error", "details": str(e)}), 500


# GET /api/reports - Fetch all reports (supports query filtering)
@app.route('/api/reports', methods=['GET'])
def get_reports():
    trial_filter = request.args.get('trial_id')
    status_filter = request.args.get('status')

    query = ClinicalReport.query

    if trial_filter:
        query = query.filter_by(trial_id=trial_filter.strip())
    if status_filter:
        query = query.filter_by(status=status_filter.strip().upper())

    # Execute SQL SELECT with applied filters
    reports = query.order_by(ClinicalReport.created_at.desc()).all()

    return jsonify({
        "count": len(reports),
        "data": [report.to_dict() for report in reports]
    }), 200


# GET /api/reports/<id> - Fetch a single report by primary key
@app.route('/api/reports/<int:report_id>', methods=['GET'])
def get_report(report_id):
    report = db.session.get(ClinicalReport, report_id)

    if not report:
        return jsonify({"error": f"Report with ID {report_id} not found"}), 404

    return jsonify({
        "data": report.to_dict()
    }), 200


# PUT /api/reports/<id> - Update status or findings of an existing report
@app.route('/api/reports/<int:report_id>', methods=['PUT'])
def update_report(report_id):
    report = db.session.get(ClinicalReport, report_id)
    if not report:
        return jsonify({"error": f"Report with ID {report_id} not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON request body"}), 400

    if 'status' in data:
        report.status = data['status'].strip().upper()
    if 'findings' in data:
        report.findings = data['findings'].strip()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Database error", "details": str(e)}), 500

    return jsonify({
        "message": f"Report {report_id} updated successfully",
        "data": report.to_dict()
    }), 200


# DELETE /api/reports/<id> - Remove a report from the database
@app.route('/api/reports/<int:report_id>', methods=['DELETE'])
def delete_report(report_id):
    report = db.session.get(ClinicalReport, report_id)
    if not report:
        return jsonify({"error": f"Report with ID {report_id} not found"}), 404

    try:
        db.session.delete(report)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Database error", "details": str(e)}), 500

    return jsonify({
        "message": f"Report {report_id} deleted successfully"
    }), 200


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)