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

def initialize_blend_breakdown(tanks):
    """Set blend_breakdown for each tank based on initial state."""
    for tank in tanks:
        if "blend_breakdown" not in tank or not tank["blend_breakdown"]:
            if tank.get("blend") and float(tank.get("current_volume", 0)) > 0:
                tank["blend_breakdown"] = {tank["blend"]: float(tank["current_volume"])}
            else:
                tank["blend_breakdown"] = {}

def transfer_wine(donor, recipient, volume):
    """Transfer wine from donor to recipient, updating blend_breakdown."""
    donor_vol = float(donor["current_volume"])
    recipient_vol = float(recipient.get("current_volume", 0))
    donor_breakdown = donor.get("blend_breakdown", {})
    if not donor_breakdown:
        donor_breakdown = {donor.get("blend", "Unknown"): donor_vol}
    # Compute breakdown for this transfer
    transfer_breakdown = {}
    for blend, amt in donor_breakdown.items():
        # Avoid divide by zero
        transfer_breakdown[blend] = amt * (volume / donor_vol) if donor_vol > 0 else 0
    # Update recipient's blend_breakdown
    recipient_breakdown = recipient.get("blend_breakdown", {})
    for blend, amt in transfer_breakdown.items():
        recipient_breakdown[blend] = recipient_breakdown.get(blend, 0) + amt
    recipient["blend_breakdown"] = recipient_breakdown
    # Reduce donor's breakdown accordingly
    for blend, amt in transfer_breakdown.items():
        donor_breakdown[blend] -= amt
    donor["blend_breakdown"] = {k: v for k, v in donor_breakdown.items() if v > 1e-3}
    # Update volumes (optional, for bookkeeping)
    donor["current_volume"] = donor_vol - volume
    recipient["current_volume"] = recipient_vol + volume

def blending_is_not_needed(working_tanks, global_blend_percentages, tolerance=2.0):
    """Returns True if every tank with wine matches the global blend percentages within tolerance."""
    tanks_with_wine = [t for t in working_tanks if float(t.get('current_volume', 0)) > 0]
    if len(tanks_with_wine) == 1:
        return True
    for t in tanks_with_wine:
        breakdown = t.get("blend_breakdown", {})
        total = sum(breakdown.values())
        if total == 0:
            continue  # Skip tanks with no wine
        for blend, pct in global_blend_percentages.items():
            tank_amt = breakdown.get(blend, 0)
            tank_pct = (tank_amt / total) * 100 if total > 0 else 0
            if abs(tank_pct - pct) > tolerance:
                return False
        # Check for unknown/rogue blends
        for blend in breakdown:
            if blend not in global_blend_percentages:
                rogue_pct = (breakdown[blend] / total) * 100
                if rogue_pct > tolerance:
                    return False
    return True

def get_tank_by_name(tank_list, name):
    return next((t for t in tank_list if t['name'] == name), None)

def double_swap(tank_a, tank_b, tank_empty):
    """
    Perform a double-swap (cross-fill) between two partially full tanks (tank_a, tank_b)
    and one empty tank (tank_empty).

    Returns a list of movement actions, each a dict:
        {
            'from': tank_name,
            'to': tank_name,
            'volume': volume_to_move,
            'blend_breakdown': {blend: volume, ...}  # for accurate record keeping
        }
    Does not update the original tanks (pure function).
    """
    moves = []

    va = tank_a['current_volume']
    vb = tank_b['current_volume']

    # Step 1: Move half of the first tank's current volume to an empty tank
    move_a_to_e = va / 2
    moves.append({
        'from': tank_a['name'],
        'to': tank_empty['name'],
        'volume': move_a_to_e,
        'blend_breakdown': {k: v * (move_a_to_e / va) for k, v in tank_a['blend_breakdown'].items()},
    })

    # Step 2: Move half of the second tank's current volume to the empty tank as above
    move_b_to_e = vb / 2
    moves.append({
        'from': tank_b['name'],
        'to': tank_empty['name'],
        'volume': move_b_to_e,
        'blend_breakdown': {k: v * (move_b_to_e / vb) for k, v in tank_b['blend_breakdown'].items()},
    })

    # Step 3: Move all remaining wine from the first tank to the second tank
    move_a_to_b = va - move_a_to_e
    moves.append({
        'from': tank_a['name'],
        'to': tank_b['name'],
        'volume': move_a_to_b,
        'blend_breakdown': {k: v * ((va - move_a_to_e) / va) for k, v in tank_a['blend_breakdown'].items()},
    })

    return moves

#def apply_transfer(tanks, move):
#    """Apply a single transfer move to the tank list in place."""
#    tank_from = next(t for t in tanks if t['name'] == move['from'])
#    tank_to = next(t for t in tanks if t['name'] == move['to'])
#
#    # Subtract volume and blend from source tank
#    tank_from['current_volume'] -= move['volume']
#    for k, v in move['blend_breakdown'].items():
#        tank_from['blend_breakdown'][k] = tank_from['blend_breakdown'].get(k, 0) - v
#        # Clean up any zero (or negative) blend components
#        if tank_from['blend_breakdown'][k] <= 0:
#            del tank_from['blend_breakdown'][k]
#
#    # Add volume and blend to destination tank
#    tank_to['current_volume'] += move['volume']
#    for k, v in move['blend_breakdown'].items():
#        tank_to['blend_breakdown'][k] = tank_to['blend_breakdown'].get(k, 0) + v

def apply_transfer(tanks, move):
    """Apply a single transfer move to the tank list in place and check feasibility."""
    tank_from = next(t for t in tanks if t['name'] == move['from'])
    tank_to = next(t for t in tanks if t['name'] == move['to'])

    max_from = float(tank_from['current_volume'])
    max_to = float(tank_to['capacity']) - float(tank_to.get('current_volume', 0))
    amount = min(move['volume'], max_from, max_to)

    if amount <= 0:
        return  # Do nothing if no valid transfer

    # Scale blend_breakdown if the transfer is less than requested
    if amount != move['volume']:
        scale = amount / move['volume']
        blend_breakdown = {k: v * scale for k, v in move['blend_breakdown'].items()}
    else:
        blend_breakdown = move['blend_breakdown']

    # Subtract volume and blend from source tank
    tank_from['current_volume'] -= amount
    for k, v in blend_breakdown.items():
        tank_from['blend_breakdown'][k] = tank_from['blend_breakdown'].get(k, 0) - v
        # Clean up any zero (or negative) blend components
        if tank_from['blend_breakdown'][k] <= 0:
            del tank_from['blend_breakdown'][k]

    # Add volume and blend to destination tank
    tank_to['current_volume'] += amount
    for k, v in blend_breakdown.items():
        tank_to['blend_breakdown'][k] = tank_to['blend_breakdown'].get(k, 0) + v

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
    # Check for each blend: is there enough in source to meet ratio in targets?
    for blend, pct in target_ratios.items():
        required = (pct / 100) * total_required
        available = sum(float(t['current_volume']) for t in source_tanks if normalize_blend(t['blend']) == blend)
        if available + 1e-3 < required:  # Small epsilon for float tolerance
            return False
    return True

def consolidate_tanks_any_blend(tanks):
    consolidation_steps = []
    # Donors: all tanks that are not empty
    donors = [t for t in tanks if float(t['current_volume']) > 0]
    # Recipients: only partially filled tanks (not empty, not full)
    recipients = [
        t for t in tanks
        if 0 < float(t['current_volume']) < float(t['capacity'])
    ]

    # Sort donors by increasing volume (empty the smallest first),
    # recipients by decreasing available space
    donors = sorted(donors, key=lambda t: float(t['current_volume']))
    recipients = sorted(recipients, key=lambda t: (float(t['capacity']) - float(t['current_volume'])), reverse=True)

    for donor in donors:
        donor_vol = float(donor['current_volume'])
        donor_blend = donor.get('blend', '')
        if donor_vol == 0:
            continue
        for recipient in recipients:
            if donor['name'] == recipient['name']:
                continue
            rec_space = float(recipient['capacity']) - float(recipient['current_volume'])
            if rec_space >= donor_vol:
                # Determine blend labeling
                rec_blend = recipient.get('blend', '')
                if rec_blend and rec_blend != donor_blend:
                    recipient['blend'] = "Mixed"
                else:
                    recipient['blend'] = donor_blend
                blend_label = donor_blend if donor_blend else "Mixed"
                # Do the transfer
                transfer_wine(donor, recipient, donor_vol)
                consolidation_steps.append({
                    'from': donor['name'],
                    'to': recipient['name'],
                    'blend': blend_label,
                    'volume': donor_vol,
                    'type': 'consolidation'
                })
                break  # donor is empty now
    return consolidation_steps

@app.route('/blend/plan', methods=['GET'])
def generate_blend_plan():
    import copy
    import random

    def approx_equal(a, b, tol=2.0):
        return abs(a - b) <= tol

    # Calculate global blend ratios before any consolidation/blending
    blend_totals = {}
    total_wine = 0
    for t in tanks:
        blend = normalize_blend(t.get('blend', ''))
        gal = float(t.get('current_volume', 0))
        if not t.get('is_empty', False) and gal > 0 and blend:
            blend_totals[blend] = blend_totals.get(blend, 0) + gal
            total_wine += gal
    blend_percentages = {blend: (gal / total_wine) * 100 for blend, gal in blend_totals.items()}

    # Prepare tank data
    working_tanks = copy.deepcopy(tanks)
    initialize_blend_breakdown(working_tanks)

    # --- CONSOLIDATION STEP START ---

    # Identify empty tanks and sort largest to smallest
    empty_tanks = [t for t in working_tanks if t['is_empty'] or float(t.get('current_volume', 0)) == 0]
    empty_tanks = sorted(empty_tanks, key=lambda t: -float(t['capacity']))

    # Identify non-empty tanks (sources)
    source_tanks = [t for t in working_tanks if not t['is_empty'] and float(t.get('current_volume', 0)) > 0]

    consolidation_transfer_plan = []
    wine_left = total_wine
    consolidation_tanks = []
    performed_consolidation = False

    if empty_tanks and float(empty_tanks[0]['capacity']) >= total_wine:
        # All wine fits in the largest empty tank - do consolidation
        consolidation_tanks = [{'tank': empty_tanks[0], 'amount': total_wine}]
        performed_consolidation = True
    elif empty_tanks:
        # Try to use multiple empty tanks for consolidation
        tanks_needed = []
        wine_left_tmp = wine_left
        for t in empty_tanks:
            if wine_left_tmp <= 0:
                break
            fill_amt = min(float(t['capacity']), wine_left_tmp)
            tanks_needed.append({'tank': t, 'amount': fill_amt})
            wine_left_tmp -= fill_amt
        if wine_left_tmp <= 0:
            consolidation_tanks = tanks_needed
            performed_consolidation = True
        else:
            # Not enough empty tank space for consolidation, skip to blending/double-swap logic
            consolidation_tanks = []
            consolidation_transfer_plan = []
            # Do not update tanks; proceed
    else:
        # No empty tanks; skip to blending/double-swap logic
        consolidation_tanks = []
        consolidation_transfer_plan = []

    # Only perform the consolidation if it actually fits
    if performed_consolidation and consolidation_tanks:
        # Move all wine into consolidation tanks using global blend proportions
        blend_left = {b: blend_totals[b] for b in blend_totals}
        wine_left = total_wine
        for entry in consolidation_tanks:
            t = entry['tank']
            amt_needed = entry['amount']
            blend_fill = {blend: amt_needed * pct / 100 for blend, pct in blend_percentages.items()}

            for blend, amount in blend_fill.items():
                amt_to_pull = amount
                source_candidates = [s for s in source_tanks if s.get('blend_breakdown', {}).get(blend, 0) > 0]
                for src in source_candidates:
                    available = src.get('blend_breakdown', {}).get(blend, 0)
                    move = min(available, amt_to_pull)
                    if move <= 0:
                        continue
                    transfer_wine(src, t, move)
                    consolidation_transfer_plan.append({
                        'from': src['name'],
                        'to': t['name'],
                        'blend': blend,
                        'volume': move,
                        'type': 'consolidation'
                    })
                    amt_to_pull -= move
                    blend_left[blend] -= move
                    wine_left -= move
                    if amt_to_pull <= 1e-6:
                        break
                if amt_to_pull > 1e-3:
                    return jsonify({'message': f'Not enough {blend} to consolidate.'}), 400
            t['is_empty'] = False
            t['current_volume'] = sum(blend_fill.values())
            t['blend_breakdown'] = blend_fill.copy()
        # All other tanks should now be empty except consolidation_tanks
        for t in working_tanks:
            if t not in [entry['tank'] for entry in consolidation_tanks]:
                t['is_empty'] = True
                t['current_volume'] = 0
                t['blend_breakdown'] = {}
   
    # --- CONSOLIDATION STEP END ---

    # Update partial/full/empty tanks after consolidation
    partial_tanks = [t for t in working_tanks if not t['is_empty'] and 0 < float(t.get('current_volume', 0)) < float(t['capacity'])]
    full_tanks = [t for t in working_tanks if not t['is_empty'] and float(t.get('current_volume', 0)) > 0]
    empty_tanks = [t for t in working_tanks if t['is_empty'] or float(t.get('current_volume', 0)) == 0]

    # Check if further blending is needed
    if blending_is_not_needed(working_tanks, blend_percentages):
        blend_gallons = {blend: round(gal, 4) for blend, gal in blend_totals.items()}
        blend_percentages_out = {blend: round((gal / total_wine) * 100, 4) for blend, gal in blend_totals.items()}
        return jsonify({
            'transfer_plan': consolidation_transfer_plan,
            'blend_percentages': blend_percentages_out,
            'blend_gallons': blend_gallons,
            'total_gallons': round(total_wine, 4),
            'message': 'Consolidation completed; no further blending needed.'
        })

    # --- BLEND LOGIC ---

    def get_tank_by_name(tank_list, name):
        return next((t for t in tank_list if t['name'] == name), None)

    best_plan = None
    best_num_tanks = float('inf')
    best_num_transfers = float('inf')

    for attempt in range(100):
        shuffled_empties = copy.deepcopy(empty_tanks)
        random.shuffle(shuffled_empties)

        trial_tanks = copy.deepcopy(full_tanks) + copy.deepcopy(empty_tanks)
        for t in trial_tanks:
            if "blend_breakdown" not in t or not t["blend_breakdown"]:
                if t.get("blend") and float(t.get("current_volume", 0)) > 0:
                    t["blend_breakdown"] = {t["blend"]: float(t["current_volume"])}
                else:
                    t["blend_breakdown"] = {}

        blend_left = {b: blend_totals[b] for b in blend_totals}
        wine_left = total_wine

        plan = copy.deepcopy(consolidation_transfer_plan)

        # Check for double-swap potential and add to blend plan if possible
        if len(full_tanks) >= 2 and len(empty_tanks) >= 1:
            tank_a, tank_b = random.sample(full_tanks,2)
            tank_empty = empty_tanks[0]
            moves = double_swap(tank_a, tank_b, tank_empty)
            for move in moves:
                apply_transfer(tanks, move)
                best_plan.append(move)

        # Move wine into empty tanks according to blend percentages
        for etank in shuffled_empties:
            if wine_left <= 0:
                break

            tank_capacity = float(etank['capacity']) - float(etank.get('current_volume', 0))
            if tank_capacity <= 0:
                continue

            fill_amount = min(tank_capacity, wine_left)

            blend_fill = {}
            limiting = False
            for blend, pct in blend_percentages.items():
                need = fill_amount * pct / 100
                if blend_left[blend] < need:
                    limiting = True
                    break
                blend_fill[blend] = need

            if limiting:
                fill_max = min(
                    blend_left[blend] / (pct / 100) if pct > 0 else float('inf')
                    for blend, pct in blend_percentages.items()
                )
                fill_amount = min(fill_amount, fill_max)
                blend_fill = {blend: fill_amount * pct / 100 for blend, pct in blend_percentages.items()}
                if fill_amount <= 0:
                    continue

            # Always use the actual etank in trial_tanks
            etank_trial = get_tank_by_name(trial_tanks, etank['name'])
            if not etank_trial:
                etank_trial = copy.deepcopy(etank)
                etank_trial["blend_breakdown"] = {}
                trial_tanks.append(etank_trial)
            else:
                if "blend_breakdown" not in etank_trial or not etank_trial["blend_breakdown"]:
                    etank_trial["blend_breakdown"] = {}

            # For each blend, draw wine from source tanks and transfer
            for blend, amount in blend_fill.items():
                to_transfer = amount
                trial_sources = [
                    t for t in trial_tanks
                    if float(t.get('current_volume', 0)) > 0 and t.get('blend_breakdown', {}).get(blend, 0) > 0
                ]
                trial_sources.sort(key=lambda t: -float(t['current_volume']))
                for src in trial_sources:
                    if to_transfer <= 0:
                        break
                    available = float(src['current_volume'])
                    move = min(available, to_transfer)
                    if move <= 0:
                        continue
                    transfer_wine(src, etank_trial, move)
                    plan.append({
                        'from': src['name'],
                        'to': etank_trial['name'],
                        'blend': blend,
                        'volume': move
                    })
                    blend_left[blend] -= move
                    wine_left -= move
                    to_transfer -= move

        # Empty the original source tanks (they should be zero after transferring all wine)
        source_tank_names = [t['name'] for t in full_tanks]
        for t in trial_tanks:
            if t['name'] in source_tank_names:
                t['current_volume'] = 0
                t['blend_breakdown'] = {}

        # Only check blend ratios for tanks that have wine (should be the previously empty tanks)
        tanks_with_wine = [t for t in trial_tanks if float(t.get('current_volume', 0)) > 0]
        if blending_is_not_needed(tanks_with_wine, blend_percentages, tolerance=2.0):
            if len(tanks_with_wine) <= best_num_tanks:
                if len(tanks_with_wine) < best_num_tanks or len(plan) < best_num_transfers:
                    best_plan = copy.deepcopy(plan)
                    best_num_tanks = len(tanks_with_wine)
                    best_num_transfers = len(plan)

        print("==== BLEND DEBUG ====")
        print("blend_totals:", blend_totals)
        print("blend_percentages:", blend_percentages)
        print("Attempted plans:", attempt+1)
        print("Last blend_left:", blend_left)
        print("Last wine_left:", wine_left)
        print("Tanks at end of last attempt:")
        for t in trial_tanks:
            print(f"  {t['name']}: vol={t.get('current_volume', 0)}, breakdown={t.get('blend_breakdown', {})}")
        print("blending_is_not_needed:", blending_is_not_needed([t for t in trial_tanks if float(t.get('current_volume', 0)) > 0], blend_percentages, tolerance=2.0))

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