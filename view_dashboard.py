"""
LangSmith Cost Dashboard Generator
Creates an interactive HTML dashboard showing cost tracking, performance metrics, and QA validation
"""

import json
from pathlib import Path
from datetime import datetime


def generate_dashboard(reports_dir="reports"):
    """Generate HTML dashboard from cost and master summary reports"""

    reports_path = Path(reports_dir)
    cost_report_file = reports_path / "cost_report.json"
    master_summary_file = reports_path / "master_summary.json"

    # Load reports
    if not cost_report_file.exists():
        print(f"[ERROR] Cost report not found: {cost_report_file}")
        return

    with open(cost_report_file, 'r') as f:
        cost_data = json.load(f)

    master_data = {}
    if master_summary_file.exists():
        with open(master_summary_file, 'r') as f:
            master_data = json.load(f)

    # Generate HTML
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SFDC Dedup Agent - LangSmith Dashboard</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 30px;
        }}
        h1 {{
            color: #667eea;
            margin-top: 0;
            border-bottom: 3px solid #667eea;
            padding-bottom: 15px;
        }}
        h2 {{
            color: #764ba2;
            margin-top: 30px;
            border-left: 4px solid #764ba2;
            padding-left: 15px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .stat-value {{
            font-size: 36px;
            font-weight: bold;
            margin: 10px 0;
        }}
        .stat-label {{
            font-size: 14px;
            opacity: 0.9;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .phase-breakdown {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
        }}
        .phase-item {{
            display: flex;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid #dee2e6;
        }}
        .phase-item:last-child {{
            border-bottom: none;
        }}
        .phase-name {{
            font-weight: 600;
            color: #495057;
        }}
        .phase-stats {{
            color: #6c757d;
            font-size: 14px;
        }}
        .metric-row {{
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #e9ecef;
        }}
        .metric-label {{
            font-weight: 500;
        }}
        .metric-value {{
            color: #667eea;
            font-weight: 600;
        }}
        .timestamp {{
            text-align: right;
            color: #6c757d;
            font-size: 12px;
            margin-top: 20px;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        .badge-success {{
            background: #28a745;
            color: white;
        }}
        .badge-warning {{
            background: #ffc107;
            color: #333;
        }}
        .badge-info {{
            background: #17a2b8;
            color: white;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 SFDC Deduplication Agent - LangSmith Dashboard</h1>

        <h2>💰 Cost Summary</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Total Cost</div>
                <div class="stat-value">${cost_data['total_cost']:.4f}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Tokens</div>
                <div class="stat-value">{cost_data['total_tokens']:,}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Runtime</div>
                <div class="stat-value">{cost_data['runtime_seconds']}s</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Cost per Minute</div>
                <div class="stat-value">${cost_data['cost_per_minute']:.4f}</div>
            </div>
        </div>

        <h2>📊 Token Breakdown</h2>
        <div class="phase-breakdown">
            <div class="metric-row">
                <span class="metric-label">Input Tokens</span>
                <span class="metric-value">{cost_data['total_input_tokens']:,}</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Output Tokens</span>
                <span class="metric-value">{cost_data['total_output_tokens']:,}</span>
            </div>
        </div>

        <h2>🔍 Cost by Phase</h2>
        <div class="phase-breakdown">
"""

    for phase, stats in cost_data['calls_by_phase'].items():
        if stats['count'] > 0:
            html += f"""
            <div class="phase-item">
                <div>
                    <span class="phase-name">{phase.replace('_', ' ').title()}</span>
                    <span class="badge badge-info">{stats['count']} calls</span>
                </div>
                <div class="phase-stats">
                    ${stats['cost']:.4f} | {stats['tokens']:,} tokens
                </div>
            </div>
"""

    html += """
        </div>
"""

    # Add workflow metrics if available
    if master_data and 'metrics' in master_data:
        metrics = master_data['metrics']
        html += f"""
        <h2>📈 Workflow Metrics</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Contacts Processed</div>
                <div class="stat-value">{metrics.get('total_contacts', 0)}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Account Owners</div>
                <div class="stat-value">{metrics.get('total_owners', 0)}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Emails Validated</div>
                <div class="stat-value">{metrics.get('emails_validated', 0)}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Duplicates Found</div>
                <div class="stat-value">{metrics.get('duplicates_found', 0)}</div>
            </div>
        </div>

        <h2>✅ Salesforce Updates</h2>
        <div class="phase-breakdown">
            <div class="metric-row">
                <span class="metric-label">Successful Updates</span>
                <span class="metric-value">{metrics.get('sfdc_updates', 0)}</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Errors</span>
                <span class="metric-value">{len(metrics.get('errors', []))}</span>
            </div>
        </div>
"""

    # Add email validation stats if available
    if master_data and 'email_validation_stats' in master_data:
        email_stats = master_data['email_validation_stats']
        html += f"""
        <h2>📧 Email Validation Stats</h2>
        <div class="phase-breakdown">
            <div class="metric-row">
                <span class="metric-label">Valid Emails</span>
                <span class="metric-value badge badge-success">{email_stats.get('Valid', 0)}</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Invalid Emails</span>
                <span class="metric-value badge badge-warning">{email_stats.get('Invalid', 0)}</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Unknown Status</span>
                <span class="metric-value">{email_stats.get('Unknown', 0)}</span>
            </div>
        </div>
"""

    # Add duplicate detection stats if available
    if master_data and 'duplicate_detection' in master_data:
        dup_stats = master_data['duplicate_detection']
        html += f"""
        <h2>🔄 Duplicate Detection</h2>
        <div class="phase-breakdown">
            <div class="metric-row">
                <span class="metric-label">Total Duplicate Pairs</span>
                <span class="metric-value">{dup_stats.get('total_pairs', 0)}</span>
            </div>
"""

        if 'by_confidence' in dup_stats:
            for confidence, count in dup_stats['by_confidence'].items():
                badge_class = {
                    'high': 'badge-success',
                    'medium': 'badge-warning',
                    'low': 'badge-info'
                }.get(confidence, 'badge-info')

                html += f"""
            <div class="metric-row">
                <span class="metric-label">{confidence.title()} Confidence</span>
                <span class="metric-value badge {badge_class}">{count}</span>
            </div>
"""

        html += """
        </div>
"""

    html += f"""
        <div class="timestamp">
            Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |
            Report Timestamp: {cost_data.get('timestamp', 'N/A')}
        </div>
    </div>
</body>
</html>
"""

    # Save dashboard
    dashboard_file = reports_path / "dashboard.html"
    with open(dashboard_file, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"[OK] Dashboard generated: {dashboard_file}")
    print(f"\nOpen this file in your browser to view the dashboard:")
    print(f"  file:///{dashboard_file.resolve()}")

    return dashboard_file


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate LangSmith Cost Dashboard")
    parser.add_argument("--reports-dir", default="reports", help="Directory containing reports")

    args = parser.parse_args()

    generate_dashboard(args.reports_dir)
