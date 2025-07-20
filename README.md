# Wine Blending Web App

This is a web application for planning and executing optimal wine blending operations. It helps winemakers efficiently consolidate and blend wines from various filled tanks (partially and fully) as well as empty tanks to achieve precisely homogenous target blends, minimizing transfers and maximizing accuracy.

## Features

- **Tank Management:**  
  - Add, edit, delete, and import/export tanks with tank name, blend code, wine volume, and capacity.
- **Blend Validation:**  
  - Calculate current blend ratios based on tank contents.
- **Blend Planning:**  
  - Generate a step-by-step transfer plan to consolidate and blend wine according to a global target ratio.
  - Supports automatic consolidation into the largest tank(s) when possible.
- **Blend History:**  
  - Save and retrieve historical blend plans.
- **CSV Import:**  
  - Easily import tank data or export current tank state.
- **User-friendly Interface:**  
  - React frontend for easy interaction.

## Technology Stack

- **Backend:** Python (Flask, Flask-CORS, Pandas)
- **Frontend:** React (served from `/build`)
- **Data Storage:** In-memory (ephemeral) for tanks, JSON file for blend history

## Getting Started

### Prerequisites

- Python 3.0+
- pip (Python package manager)
- Node.js & npm (if developing REACT frontend)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/bcrawford89/Bryces-Blender.git
   cd "Bryces Blender"
   ```

2. **Backend Setup:**
   ```bash
   pip install -r requirements.txt
   python app.py
   ```
   The backend will run on [http://localhost:5000](http://localhost:5000).

3. **Frontend Setup (Development):**
   ```bash
   cd frontend
   npm install
   npm run build
   ```
   The production frontend will be served by Flask from the `/build` directory.

### Usage

1. **Access the Web App:**  
   Open [http://localhost:5000](http://localhost:5000) in your browser.

2. **Manage Tanks:**  
   Add new tanks manually or upload a CSV file with your tank data.

3. **Validate Blends:**  
   Use the "Blend Percentages" feature to see the current blend ratios. This acts as a logic check for the user before computing the most optimal blending plan. 

4. **Generate Blending Plan:**  
   Use the "Generate Blending Plan" to allow the app to generate the optimal blending plan.  
   The app will:
   - Consolidate wine blends into the largest tank or tanks if possible.
   - Split the blend into final tanks, ensuring accuracy within a fractional tolerance.

5. **Save/Load Blend Plans:**  
   Save the blending plans by creating a new blend name and using the "Save Blend" button for documentation or repeat operations.

### CSV Format

| Tank Name | Blend Number | Is Empty | Current Volume (gal) | Capacity (gal) |
|-----------|--------------|----------|----------------------|----------------|
| exTank1   | exBlend1     | No       | exGallons1           | exCapacity1    |
| exTank2   |              | Yes      | 0                    | exCapacity2    |
etc... All headers must be written exactly as above.

- **Is Empty**: Accepts "Yes", "No", "True", "False", "1", "0". This helps the consolidation step to function accurately.

### API Endpoints

- `GET /tanks` – List all tanks
- `POST /tanks` – Add a new tank
- `PUT /tanks/<tank_name>` – Edit a tank
- `DELETE /tanks/<tank_name>` – Delete a tank
- `GET /tanks/export` – Export tanks as CSV
- `POST /upload` – Import tanks from CSV
- `GET /blend/validate` – Get current blend ratios
- `GET /blend/plan` – Generate blending transfer plan
- `POST /blend/save` – Save a blend plan
- `GET /blend/history` – List saved plans
- `GET /blend/history/<name>` – Get a saved plan

### Development

- To make backend or frontend changes, edit the respective files and restart the Flask server.
- All static files are served from the `/build` directory.

## License

MIT License (Author attribution, please.)

# Authors

- Bryce Crawford
- Contributors: Github Copilot

# NB

- All bugs and comments/suggestions can be sent to bryceecrawford@gmail.com

---

*This project streamlines homogenous wine blending for small and large wineries, minimizing labor and maximizing blend quality!*