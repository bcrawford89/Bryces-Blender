from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from collections import defaultdict
import pandas as pd
import csv
import io
import os
import json

app = Flask(__name__, static_folder="build", static_url_path="/")
CORS(app)

# Appendable files for data
DATA_FILE = 'tanks.json'
HISTORY_FILE = 'blend_history.json'

# In-memory storage for tanks
tanks = {}

# Helper to normalize blend numbers and tank names (case-insensitive)
def normalize_blend(blend):
    return blend.lower() if blend else None

def normalize_tank_name(name):
    return name.lower() if name else None

# Helpers for tank functions and history
def load_tanks():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, 'r') as f:
        return json.load(f)

def save_tanks(tanks):
    with open(DATA_FILE, 'w') as f:
        json.dump(tanks, f)

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, 'r') as f:
        return json.load(f)

def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f)

# Route to list all tanks
## COULD BE GET_TANKS not list_tanks ####### 
@app.route('/tanks', methods=['GET'])
def list_tanks():
    return jsonify(list(tanks.values()))

# Route to add a new tank
@app.route('/tanks', methods=['POST'])
def add_tank():
    tanks = load_tanks()
    data = request.json
    tanks.append(data)
    tank_name = normalize_tank_name(data['name'])
    if tank_name in tanks:
        return jsonify({"error": "Tank already exists."}), 400
    else:
        return jsonify({'message': 'Tank added'})

    tanks[tank_name] = {
        "name": data['name'],
        "blend": normalize_blend(data.get('blend')),
        "is_empty": data.get('is_empty', True),
        "current_volume": float(data.get('current_volume', 0)),
        "capacity": float(data.get('capacity', 0))
    }
    save_tanks(tanks)
    return jsonify(tanks[tank_name]), 201

# Route to edit an existing tank
@app.route('/tanks/<tank_name>', methods=['PUT'])
def edit_tank(tank_name):
    norm_name = normalize_tank_name(tank_name)
    if norm_name not in tanks:
        return jsonify({"error": "Tank not found."}), 404

    data = request.json
    tank = tanks[norm_name]

    tank['blend'] = normalize_blend(data.get('blend', tank['blend']))
    tank['is_empty'] = data.get('is_empty', tank['is_empty'])
    tank['current_volume'] = float(data.get('current_volume', tank['current_volume']))
    tank['capacity'] = float(data.get('capacity', tank['capacity']))

    save_tanks(tanks)
    return jsonify(tank)

# Route to delete a tank
@app.route('/tanks/<tank_name>', methods=['DELETE'])
def delete_tank(tank_name):
    norm_name = normalize_tank_name(tank_name)
    if norm_name not in tanks:
        return jsonify({"error": "Tank not found."}), 404
    del tanks[norm_name]
    save_tanks(tanks)
    return jsonify({"message": f"Tank '{tank_name}' deleted."})

# Route to export tank data as CSV
@app.route('/tanks/export', methods=['GET'])
def export_csv():
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["name", "blend", "is_empty", "current_volume", "capacity"])
    writer.writeheader()
    for tank in tanks.values():
        writer.writerow(tank)
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name='tanks.csv')

# OLD Route to import tank data from CSV
# @app.route('/tanks/import', methods=['POST'])
# def import_csv():
#     if 'file' not in request.files:
#         return 'No file part', 400
#     file = request.files['file']
#     if file.filename == '':
#         return 'No selected file', 400
# 
#     df = pd.read_csv(file)
#     tanks.clear()
#     for _, row in df.iterrows():
#         tank = {
#             'name': str(row['Tank Name']).strip(),
#             'blend': str(row['Blend Number']).strip() if pd.notna(row['Blend Number']) else '',
#             'is_empty': row['Is Empty'].strip().lower() == 'yes',
#             'current_volume': float(row['Current Volume (gal)']) if pd.notna(row['Current Volume (gal)']) else 0.0,
#             'capacity': float(row['Capacity (gal)']) if pd.notna(row['Capacity (gal)']) else 0.0
#         }
#         tanks.append(tank)
#     return 'CSV Tanks uploaded successfully', 200

app.config['TANKS'] = []

@app.route('/upload', methods=['POST'])
def upload_csv():
    file = request.files['file']
    if not file:
        return jsonify({'error': 'No file provided'}), 400
    try:
        df = pd.read_csv(file)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    tanks = []
    for _, row in df.iterrows():
        tank = {
            'name': str(row['Tank Name']).strip(),
            'blend': str(row['Blend Number']).strip(),
            'is_empty': str(row['Is Empty']).lower() in ['yes', 'true', '1'],
            'current_volume': float(row['Current Volume (gal)']),
            'capacity': float(row['Capacity (gal)']),
        }
        tanks.append(tank)

    app.config['TANKS'] = tanks
    save_tanks(tanks)
    return jsonify({'message': 'Upload successful!'})

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react_app(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

# Route to validate blend
# this calculates global blend percentages across non-empty tanks
@app.route('/blend/validate', methods=['GET'])
def validate_blend():
    tanks = load_tanks()
    total_volume = 0
    blend_totals = {}

    for tank in tanks:
        if not tank['is_empty']:
            volume = float(tank.get('current_volume', 0))
            blend = tank.get('blend', '').strip()

            if blend:
                total_volume += volume
                blend_totals[blend] = blend_totals.get(blend, 0) + volume

    if total_volume == 0:
        return jsonify({'message': 'No wine to calculate blend'}), 400

    # Calculate percentages
    blend_percentages = {
        blend: (vol / total_volume) * 100 for blend, vol in blend_totals.items()
    }

    return jsonify({'blend_percentages': blend_percentages})

@app.route('/blend/plan', methods=['GET'])
def generate_blend_plan():
    tanks = load_tanks()
    full_tanks = [t for t in tanks if not t['is_empty'] and float(t['current_volume']) > 0]
    empty_tanks = [t for t in tanks if t['is_empty'] or float(t['current_volume']) == 0]

    total_volume = sum(float(t['current_volume']) for t in full_tanks)
    blend_totals = {}
    for t in full_tanks:
        blend = t['blend']
        volume = float(t['current_volume'])
        blend_totals[blend] = blend_totals.get(blend, 0) + volume

    blend_percentages = {
        blend: round(vol / total_volume * 100, 4) for blend, vol in blend_totals.items()
    }

    plan = []
    updated_tanks = {t['name']: t.copy() for t in tanks}

    for etank in empty_tanks:
        capacity = float(etank['capacity'])
        required_volumes = {
            blend: round((pct / 100) * capacity, 4) for blend, pct in blend_percentages.items()
        }

        used_sources = set()
        for blend, vol in required_volumes.items():
            available_sources = [t for t in full_tanks if t['blend'] == blend and t['name'] not in used_sources]
            transferred = 0

            for source in sorted(available_sources, key=lambda t: -float(t['current_volume'])):
                source_vol = float(source['current_volume'])
                move_vol = min(source_vol, vol - transferred)
                if move_vol <= 0:
                    continue

                plan.append({
                    'from': source['name'],
                    'to': etank['name'],
                    'blend': blend,
                    'volume': move_vol
                })

                updated_tanks[source['name']]['current_volume'] = round(source_vol - move_vol, 4)
                updated_tanks[etank['name']]['blend'] = 'Mixed'
                updated_tanks[etank['name']]['is_empty'] = False
                updated_tanks[etank['name']]['current_volume'] = round(float(updated_tanks[etank['name']].get('current_volume', 0)) + move_vol, 4)

                transferred += move_vol
                used_sources.add(source['name'])
                if abs(transferred - vol) < 0.001:
                    break

        if abs(sum(required_volumes.values()) - float(updated_tanks[etank['name']]['current_volume'])) > 0.001:
            return jsonify({'message': 'Insufficient wine to match blend ratios exactly'}), 400

    return jsonify({
        'transfer_plan': plan,
        'blend_percentages': blend_percentages
    })

@app.route('/blend/save', methods=['POST'])
def save_blend():
    data = request.json
    history = load_history()
    history[data['blend_name']] = {
        'transfer_plan': data['transfer_plan'],
        'blend_percentages': data['blend_percentages']
    }
    save_history(history)
    return jsonify({'message': 'Blend plan saved'})

@app.route('/blend/history', methods=['GET'])
def list_history():
    return jsonify(list(load_history().keys()))

@app.route('/blend/history/<name>', methods=['GET'])
def get_history(name):
    history = load_history()
    if name in history:
        return jsonify(history[name])
    return jsonify({'message': 'Blend history not found'}), 404

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))  # Render sets the PORT env variable
    app.run(host='0.0.0.0', port=port)
