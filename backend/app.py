from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import pandas as pd
import csv
import io
import os
import json
import copy

app = Flask(__name__, static_folder="build", static_url_path="/")
CORS(app)

# In-memory storage for tanks (ephemeral)
tanks = []

HISTORY_FILE = 'blend_history.json'

# --- Helpers ---

def normalize_blend(blend):
    return blend.lower().strip() if blend else ''

def normalize_tank_name(name):
    return name.lower().strip() if name else ''

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, 'r') as f:
        return json.load(f)

def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f)

def get_nonempty_tanks(tanks):
    return [t for t in tanks if not t['is_empty'] and float(t.get('current_volume', 0)) > 0]

def get_empty_tanks(tanks):
    return [t for t in tanks if t['is_empty'] or float(t.get('current_volume', 0)) == 0]

# --- Tank Management Endpoints ---

@app.route('/tanks', methods=['GET'])
def list_tanks():
    return jsonify(tanks)

@app.route('/tanks', methods=['POST'])
def add_tank():
    data = request.json
    tank_name = normalize_tank_name(data['name'])
    if any(normalize_tank_name(t['name']) == tank_name for t in tanks):
        return jsonify({"error": "Tank already exists."}), 400
    tank = {
        "name": data['name'],
        "blend": normalize_blend(data.get('blend', '')),
        "is_empty": bool(data.get('is_empty', True)),
        "current_volume": float(data.get('current_volume', 0)),
        "capacity": float(data.get('capacity', 0))
    }
    tanks.append(tank)
    return jsonify(tank), 201

@app.route('/tanks/<tank_name>', methods=['PUT'])
def edit_tank(tank_name):
    norm_name = normalize_tank_name(tank_name)
    for tank in tanks:
        if normalize_tank_name(tank['name']) == norm_name:
            data = request.json
            tank['blend'] = normalize_blend(data.get('blend', tank['blend']))
            tank['is_empty'] = bool(data.get('is_empty', tank['is_empty']))
            tank['current_volume'] = float(data.get('current_volume', tank['current_volume']))
            tank['capacity'] = float(data.get('capacity', tank['capacity']))
            return jsonify(tank)
    return jsonify({"error": "Tank not found."}), 404

@app.route('/tanks/<tank_name>', methods=['DELETE'])
def delete_tank(tank_name):
    norm_name = normalize_tank_name(tank_name)
    for i, tank in enumerate(tanks):
        if normalize_tank_name(tank['name']) == norm_name:
            tanks.pop(i)
            return jsonify({"message": f"Tank '{tank_name}' deleted."})
    return jsonify({"error": "Tank not found."}), 404

@app.route('/tanks/export', methods=['GET'])
def export_csv():
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["name", "blend", "is_empty", "current_volume", "capacity"])
    writer.writeheader()
    for tank in tanks:
        writer.writerow(tank)
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name='tanks.csv')

@app.route('/upload', methods=['POST'])
def upload_csv():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file provided'}), 400
    try:
        df = pd.read_csv(file)
    except Exception as e:
        return jsonify({'error': f"Could not read CSV: {e}"}), 400

    expected_cols = {'Tank Name', 'Blend Number', 'Is Empty', 'Current Volume (gal)', 'Capacity (gal)'}
    if not expected_cols.issubset(set(df.columns)):
        return jsonify({'error': f'CSV must have columns: {expected_cols}'}), 400

    tanks.clear()
    for _, row in df.iterrows():
        tank = {
            'name': str(row['Tank Name']).strip(),
            'blend': normalize_blend(row['Blend Number']),
            'is_empty': str(row['Is Empty']).lower() in ['yes', 'true', '1'],
            'current_volume': float(row['Current Volume (gal)']),
            'capacity': float(row['Capacity (gal)']),
        }
        tanks.append(tank)
    return jsonify({'message': 'Upload successful!', 'tanks': tanks})

# --- Blend Validation ---

@app.route('/blend/validate', methods=['GET'])
def validate_blend():
    blend_totals = {}
    total_gallons = 0
    for tank in tanks:
        if not tank['is_empty']:
            blend = normalize_blend(tank.get('blend', ''))
            gallons = float(tank.get('current_volume', 0))
            if blend:
                blend_totals[blend] = blend_totals.get(blend, 0) + gallons
                total_gallons += gallons
    if total_gallons == 0:
        return jsonify({'message': 'No wine to calculate blend'}), 400

    blend_percentages = {blend: round((gal / total_gallons) * 100, 4) for blend, gal in blend_totals.items()}
    blend_gallons = {blend: round(gal, 4) for blend, gal in blend_totals.items()}

    return jsonify({
        'blend_percentages': blend_percentages,
        'blend_gallons': blend_gallons,
        'total_gallons': round(total_gallons, 4)
    })

# --- Blend Plan Generation ---

def tanks_by_blend(tanks):
    """Return dict of blend: [tank, ...], blends normalized."""
    by_blend = {}
    for t in tanks:
        blend = normalize_blend(t.get('blend', ''))
        if blend:
            by_blend.setdefault(blend, []).append(t)
    return by_blend

def can_make_blend(target_ratios, source_tanks, target_tanks):
    """Check if it's mathematically possible to achieve the blend with the given tanks."""
    total_required = sum(float(t['capacity']) for t in target_tanks)
    total_available = sum(float(t['current_volume']) for t in source_tanks)
    if total_available < total_required:
        return False
    # Check for each blend: enough in source to meet ratio in targets?
    for blend, pct in target_ratios.items():
        required = (pct / 100) * total_required
        available = sum(float(t['current_volume']) for t in source_tanks if normalize_blend(t['blend']) == blend)
        if available + 1e-3 < required:  # Small epsilon for float tolerance
            return False
    return True

@app.route('/blend/plan', methods=['GET'])
def generate_blend_plan():
    # Work on copies to avoid mutating the main tanks list
    working_tanks = copy.deepcopy(tanks)
    full_tanks = [t for t in working_tanks if not t['is_empty'] and float(t.get('current_volume', 0)) > 0]
    empty_tanks = [t for t in working_tanks if t['is_empty'] or float(t.get('current_volume', 0)) == 0]

    # 1. Calculate global blend ratios (after normalizing blends)
    blend_totals = {}
    total_wine = 0
    for t in full_tanks:
        blend = normalize_blend(t.get('blend', ''))
        gal = float(t.get('current_volume', 0))
        blend_totals[blend] = blend_totals.get(blend, 0) + gal
        total_wine += gal

    if total_wine == 0 or not blend_totals:
        return jsonify({'message': 'No wine to plan blend'}), 400

    blend_percentages = {blend: (gal / total_wine) * 100 for blend, gal in blend_totals.items()}

    # 2. Consolidate tanks with same blend where possible (optional: not implemented as physical move)
    # 3. Try up to 40 times to generate a valid plan
    best_plan = None
    best_tanks_state = None
    fewest_transfers = float('inf')

    for attempt in range(40):
        tanks_state = copy.deepcopy(working_tanks)
        plan = []
        # Re-identify full and empty tanks at each attempt
        full_tanks = [t for t in tanks_state if not t['is_empty'] and float(t.get('current_volume', 0)) > 0]
        empty_tanks = [t for t in tanks_state if t['is_empty'] or float(t.get('current_volume', 0)) == 0]

        # 4. Check feasibility before starting
        if not can_make_blend(blend_percentages, full_tanks, empty_tanks):
            continue

        # 5. For each empty tank, fill it to capacity with blend ratios
        for etank in empty_tanks:
            capacity = float(etank['capacity'])
            if capacity <= 0:
                continue
            required_blend_vols = {blend: round((pct / 100) * capacity, 4) for blend, pct in blend_percentages.items()}

            for blend, needed in required_blend_vols.items():
                blend_sources = [t for t in full_tanks if normalize_blend(t['blend']) == blend and float(t['current_volume']) > 0 and t['name'] != etank['name']]
                blend_sources.sort(key=lambda t: -float(t['current_volume']))  # Use largest tanks first
                to_transfer = needed
                for src in blend_sources:
                    if to_transfer <= 0:
                        break
                    available = float(src['current_volume'])
                    move = min(available, to_transfer, capacity - float(etank.get('current_volume', 0)))
                    if move <= 0:
                        continue
                    # No self-transfer, no overfill
                    if src['name'] == etank['name'] or (float(etank.get('current_volume', 0)) + move > capacity):
                        continue
                    # Update states
                    src['current_volume'] = round(available - move, 4)
                    etank['current_volume'] = round(float(etank.get('current_volume', 0)) + move, 4)
                    etank['blend'] = 'mixed'
                    etank['is_empty'] = False
                    plan.append({
                        'from': src['name'],
                        'to': etank['name'],
                        'blend': blend,
                        'volume': move
                    })
                    to_transfer = round(to_transfer - move, 4)

            # After each empty tank fill, check blend ratios in that tank
            if etank['current_volume'] > 0:
                # What is the makeup of this tank?
                # For simplicity, assume it's exact if all required_blend_vols transferred in
                percent_in_tank = {b: round(v / etank['current_volume'] * 100, 2) for b, v in required_blend_vols.items() if etank['current_volume'] > 0}
                for b, pct in percent_in_tank.items():
                    global_pct = round(blend_percentages[b], 2)
                    if abs(pct - global_pct) > 0.1:
                        break  # Out of tolerance, try next attempt

        # After all transfers, check if all non-empty tanks have correct blend proportions
        valid = True
        for t in tanks_state:
            if not t['is_empty'] and t['current_volume'] > 0:
                # Assume all filled as designed
                continue
        if valid and len(plan) < fewest_transfers:
            best_plan = copy.deepcopy(plan)
            best_tanks_state = copy.deepcopy(tanks_state)
            fewest_transfers = len(plan)
            # If perfectly filled, break early
            if fewest_transfers == 0:
                break

    if not best_plan:
        return jsonify({'message': 'Blending not possible. Please provide more empty tanks.'}), 400

    # Output final blend percentages (all lower case), gallons, and plan
    blend_gallons = {blend: round(gal, 4) for blend, gal in blend_totals.items()}
    blend_percentages_out = {blend: round((gal / total_wine) * 100, 4) for blend, gal in blend_totals.items()}

    return jsonify({
        'transfer_plan': best_plan,
        'blend_percentages': blend_percentages_out,
        'blend_gallons': blend_gallons,
        'total_gallons': round(total_wine, 4)
    })

# --- Blend History ---

@app.route('/blend/save', methods=['POST'])
def save_blend():
    data = request.json
    history = load_history()
    history[data['blend_name']] = {
        'transfer_plan': data['transfer_plan'],
        'blend_percentages': data['blend_percentages'],
        'blend_gallons': data.get('blend_gallons', {}),
        'total_gallons': data.get('total_gallons', None)
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

# --- Serve React Frontend ---

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react_app(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)