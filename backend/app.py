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
        blend_val = '' if pd.isna(row['Blend Number']) else str(row['Blend Number'])
        current_volume_val = 0 if pd.isna(row['Current Volume (gal)']) else float(row['Current Volume (gal)'])
        tank = {
            'name': str(row['Tank Name']).strip(),
            'blend': normalize_blend(blend_val),
            'is_empty': str(row['Is Empty']).lower() in ['yes', 'true', '1'],
            'current_volume': current_volume_val,
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

def consolidate_tanks_any_blend(tanks):
    consolidation_steps = []
    tanks_with_wine = [t for t in tanks if float(t['current_volume']) > 0]
    tanks_with_space = [t for t in tanks if float(t['current_volume']) < float(t['capacity'])]

    # Sort by available space (smallest first)
    tanks_with_space = sorted(tanks_with_space, key=lambda t: (float(t['capacity']) - float(t['current_volume'])))
    tanks_with_wine = sorted(tanks_with_wine, key=lambda t: float(t['current_volume']))

    for donor in tanks_with_wine:
        if float(donor['current_volume']) == 0:
            continue
        for recipient in tanks_with_space:
            if donor['name'] == recipient['name']:
                continue
            available = float(recipient['capacity']) - float(recipient['current_volume'])
            if available <= 0:
                continue
            to_transfer = min(float(donor['current_volume']), available)
            if to_transfer <= 0:
                continue
            donor['current_volume'] -= to_transfer
            recipient['current_volume'] += to_transfer
            consolidation_steps.append({
                'from': donor['name'],
                'to': recipient['name'],
                'blend_from': donor.get('blend', ''),
                'blend_to': recipient.get('blend', ''),
                'volume': to_transfer
            })
            if float(donor['current_volume']) == 0:
                break
    return consolidation_steps

@app.route('/blend/plan', methods=['GET'])
def generate_blend_plan():
    import copy
    import random

    def approx_equal(a, b, tol=0.1):
        return abs(a - b) <= tol

    # Prepare tank data
    working_tanks = copy.deepcopy(tanks)
    
    # --- NEW BLEND-AGNOSTIC CONSOLIDATION STEP ---
    consolidation_plan = consolidate_tanks_any_blend(working_tanks)
    
    # Update partial/full/empty tanks after consolidation
    partial_tanks = [t for t in working_tanks if not t['is_empty'] and 0 < float(t.get('current_volume', 0)) < float(t['capacity'])]
    full_tanks = [t for t in working_tanks if not t['is_empty'] and float(t.get('current_volume', 0)) > 0]
    empty_tanks = [t for t in working_tanks if t['is_empty'] or float(t.get('current_volume', 0)) == 0]

#####This is where the old consolidation steps went#####

    # After consolidation, update working_tanks, full_tanks, empty_tanks
    for move in consolidation_plan:
        # Apply consolidation to working_tanks
        for t in working_tanks:
            if t['name'] == move['from']:
                t['current_volume'] = 0
                t['is_empty'] = True
            if t['name'] == move['to']:
                t['current_volume'] += move['volume']

    # Now recalculate full/empty after consolidation
    full_tanks = [t for t in working_tanks if not t['is_empty'] and float(t.get('current_volume', 0)) > 0]
    empty_tanks = [t for t in working_tanks if t['is_empty'] or float(t.get('current_volume', 0)) == 0]

    # --- BLEND LOGIC ---
    # 1. Calculate global blend ratios
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

    # Best plan tracking
    best_plan = None
    best_num_tanks = float('inf')
    best_num_transfers = float('inf')

    for attempt in range(40):
        # Randomize empty tank order
        shuffled_empties = copy.deepcopy(empty_tanks)
        random.shuffle(shuffled_empties)

        # Copy tank states and blend levels
        trial_tanks = copy.deepcopy(full_tanks)
        blend_left = {b: blend_totals[b] for b in blend_totals}
        wine_left = total_wine

        plan = copy.deepcopy(consolidation_plan)
        tanks_used = 0

        for etank in shuffled_empties:
            if wine_left <= 0:
                break

            tank_capacity = float(etank['capacity']) - float(etank.get('current_volume', 0))
            if tank_capacity <= 0:
                continue

            fill_amount = min(tank_capacity, wine_left)

            # Figure out how much of each blend is needed (may be limited by available blend)
            blend_fill = {}
            limiting = False
            for blend, pct in blend_percentages.items():
                need = fill_amount * pct / 100
                if blend_left[blend] < need:
                    limiting = True
                    break
                blend_fill[blend] = need

            if limiting:
                fill_max = min(blend_left[blend] / (pct / 100) if pct > 0 else float('inf')
                               for blend, pct in blend_percentages.items())
                fill_amount = min(fill_amount, fill_max)
                blend_fill = {blend: fill_amount * pct / 100 for blend, pct in blend_percentages.items()}
                if fill_amount <= 0:
                    continue

            # Actually transfer wine from source tanks into this empty tank
            etank_fill = {b: 0.0 for b in blend_percentages}
            for blend, amount in blend_fill.items():
                to_transfer = amount
                blend_left[blend] -= amount
                trial_sources = [t for t in trial_tanks if normalize_blend(t['blend']) == blend and float(t['current_volume']) > 0]
                trial_sources.sort(key=lambda t: -float(t['current_volume']))
                for src in trial_sources:
                    if to_transfer <= 0:
                        break
                    available = float(src['current_volume'])
                    move = min(available, to_transfer)
                    if move <= 0:
                        continue
                    src['current_volume'] = round(available - move, 4)
                    etank_fill[blend] += move
                    plan.append({
                        'from': src['name'],
                        'to': etank['name'],
                        'blend': blend,
                        'volume': move
                    })
                    to_transfer -= move

            total_in = sum(etank_fill.values())
            if total_in == 0:
                continue
            tank_blend = {b: (etank_fill[b] / total_in * 100) if total_in > 0 else 0 for b in blend_percentages}
            if not all(approx_equal(tank_blend[b], blend_percentages[b]) for b in blend_percentages):
                continue

            tanks_used += 1
            wine_left -= total_in

        if abs(wine_left) < 1e-2 and tanks_used <= best_num_tanks:
            if tanks_used < best_num_tanks or len(plan) < best_num_transfers:
                best_plan = copy.deepcopy(plan)
                best_num_tanks = tanks_used
                best_num_transfers = len(plan)

    if not best_plan:
        return jsonify({'message': 'Blending not possible. Please provide more empty tanks.'}), 400

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