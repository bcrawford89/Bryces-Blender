from flask import Flask, request, jsonify, send_file
from collections import defaultdict
import csv
import io

app = Flask(__name__)

# In-memory storage for tanks
tanks = {}

# Helper to normalize blend numbers and tank names (case-insensitive)
def normalize_blend(blend):
    return blend.lower() if blend else None

def normalize_tank_name(name):
    return name.lower() if name else None

# Route to list all tanks
@app.route('/tanks', methods=['GET'])
def list_tanks():
    return jsonify(list(tanks.values()))

# Route to add a new tank
@app.route('/tanks', methods=['POST'])
def add_tank():
    data = request.json
    tank_name = normalize_tank_name(data['name'])
    if tank_name in tanks:
        return jsonify({"error": "Tank already exists."}), 400

    tanks[tank_name] = {
        "name": data['name'],
        "blend": normalize_blend(data.get('blend')),
        "is_empty": data.get('is_empty', True),
        "current_volume": float(data.get('current_volume', 0)),
        "capacity": float(data.get('capacity', 0))
    }
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

    return jsonify(tank)

# Route to delete a tank
@app.route('/tanks/<tank_name>', methods=['DELETE'])
def delete_tank(tank_name):
    norm_name = normalize_tank_name(tank_name)
    if norm_name not in tanks:
        return jsonify({"error": "Tank not found."}), 404
    del tanks[norm_name]
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

# Route to import tank data from CSV
@app.route('/tanks/import', methods=['POST'])
def import_csv():
    file = request.files['file']
    if not file:
        return jsonify({"error": "No file uploaded."}), 400

    stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
    reader = csv.DictReader(stream)
    for row in reader:
        tank_name = normalize_tank_name(row['name'])
        tanks[tank_name] = {
            "name": row['name'],
            "blend": normalize_blend(row.get('blend')),
            "is_empty": row.get('is_empty', 'true').lower() == 'true',
            "current_volume": float(row.get('current_volume', 0)),
            "capacity": float(row.get('capacity', 0))
        }
    return jsonify({"message": "Tanks imported successfully."})

if __name__ == '__main__':
    app.run(debug=True)
